import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ai_engine, services
from ..config import settings
from ..database import get_db
from ..models import Cluster, Complaint, Notification, ResolutionVote, User, utcnow
from ..security import citizen_only, current_user, official_only, optional_user

router = APIRouter(prefix="/api", tags=["issues"])

ALLOWED_EXT = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".gif": "image",
               ".mp4": "video", ".webm": "video", ".mov": "video"}


def save_upload(file: UploadFile) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Only JPG, PNG, WEBP, GIF images and MP4, WEBM, MOV videos are allowed.")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / name
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File too large. Maximum is {settings.MAX_UPLOAD_MB} MB per file.")
            out.write(chunk)
    return {"url": f"/media/{name}", "type": ALLOWED_EXT[ext], "name": (file.filename or name)[:120], "_path": str(dest)}


def real_files(files: Optional[list[UploadFile]]) -> list[UploadFile]:
    return [f for f in (files or []) if f and f.filename]


def get_cluster(db: Session, cid: int) -> Cluster:
    c = db.get(Cluster, cid)
    if not c:
        raise HTTPException(404, "Issue not found.")
    return c


def ensure_department(user: User, c: Cluster):
    if user.department != c.department:
        raise HTTPException(403, f"This issue belongs to {c.department}. You can view it but only that department can act on it.")


def run_transition(db: Session, c: Cluster, user: User, stage: str, **kw):
    try:
        services.transition(db, c, user, stage, **kw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(c)


# ----------------------------------------------------------------------------- citizen
@router.post("/complaints")
def create_complaint(text: str = Form(""), lat: float = Form(...), lon: float = Form(...), address: str = Form(""),
                     files: list[UploadFile] = File(default=[]), user: User = Depends(citizen_only),
                     db: Session = Depends(get_db)):
    text, address = text.strip(), address.strip()[:300]
    uploads = real_files(files)
    if len(text) > 2000:
        raise HTTPException(400, "Description is too long (max 2000 characters).")
    if len(text) < 5 and not uploads:
        raise HTTPException(400, "Please describe the problem or attach a photo / video.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "Invalid location.")
    if len(uploads) > settings.MAX_FILES:
        raise HTTPException(400, f"You can attach up to {settings.MAX_FILES} files.")

    saved = [save_upload(f) for f in uploads]
    image_paths = [Path(s["_path"]) for s in saved if s["type"] == "image"]
    ai = ai_engine.analyze(text, address, image_paths)
    media = [{k: v for k, v in s.items() if k != "_path"} for s in saved]
    complaint, cluster, merged = services.ingest(db, user, text, lat, lon, address, media, ai)
    db.commit()
    db.refresh(cluster)
    return {"complaint_id": complaint.id, "merged": merged, "ai": ai.as_dict(), "issue": services.cluster_card(cluster)}


@router.get("/complaints/mine")
def my_complaints(user: User = Depends(citizen_only), db: Session = Depends(get_db)):
    rows = db.query(Complaint).filter(Complaint.user_id == user.id).order_by(Complaint.created_at.desc()).all()
    return [{"complaint": {"id": r.id, "text": r.text, "created_at": services.iso(r.created_at), "media": r.media or []},
             "issue": services.cluster_card(r.cluster)} for r in rows]


@router.get("/issues/{cid}")
def issue_detail(cid: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(optional_user)):
    return services.cluster_detail(get_cluster(db, cid), viewer)


class ReopenBody(BaseModel):
    reason: str = ""


@router.post("/issues/{cid}/confirm")
def confirm_fixed(cid: int, user: User = Depends(citizen_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    if c.stage != "completed":
        raise HTTPException(400, "This issue is not marked resolved yet.")
    if not db.query(Complaint).filter(Complaint.cluster_id == cid, Complaint.user_id == user.id).first():
        raise HTTPException(403, "Only citizens who reported this issue can confirm it.")
    if db.query(ResolutionVote).filter_by(user_id=user.id, cluster_id=cid, round=c.reopen_count).first():
        raise HTTPException(409, "You have already confirmed this resolution.")
    db.add(ResolutionVote(user_id=user.id, cluster_id=cid, round=c.reopen_count))
    c.confirmations += 1
    db.commit()
    return {"ok": True, "confirmations": c.confirmations}


@router.post("/issues/{cid}/reopen")
def reopen(cid: int, body: ReopenBody, user: User = Depends(citizen_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    if c.stage != "completed":
        raise HTTPException(400, "Only resolved issues can be reopened.")
    if not db.query(Complaint).filter(Complaint.cluster_id == cid, Complaint.user_id == user.id).first():
        raise HTTPException(403, "Only citizens who reported this issue can reopen it.")
    if c.resolved_at and utcnow() - c.resolved_at > timedelta(days=settings.REOPEN_WINDOW_DAYS):
        raise HTTPException(400, f"The {settings.REOPEN_WINDOW_DAYS}-day reopen window has passed. Please file a new complaint.")
    reason = (body.reason or "").strip()[:500]
    if len(reason) < 5:
        raise HTTPException(400, "Please tell us what is still wrong (at least a few words).")
    run_transition(db, c, user, "reopened", note=f"Reopened by citizen: {reason}")
    return services.cluster_detail(c, user)


# ----------------------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(30).all()
    return {"unread": sum(1 for r in rows if not r.read),
            "items": [{"id": r.id, "cluster_id": r.cluster_id, "message": r.message, "read": r.read,
                       "at": services.iso(r.created_at)} for r in rows]}


@router.post("/notifications/read")
def mark_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read == False).update({"read": True})  # noqa: E712
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- official actions
class AckBody(BaseModel):
    target_date: Optional[str] = None  # YYYY-MM-DD
    note: str = ""


class OverrideBody(BaseModel):
    category: Optional[str] = None
    sub_category: Optional[str] = None
    priority: Optional[int] = None
    clear_priority: bool = False
    reason: str = ""


@router.post("/issues/{cid}/acknowledge")
def acknowledge(cid: int, body: AckBody, user: User = Depends(official_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    ensure_department(user, c)
    target = None
    if body.target_date:
        try:
            target = datetime.strptime(body.target_date, "%Y-%m-%d") + timedelta(hours=23, minutes=59)
        except ValueError:
            raise HTTPException(400, "Target date must be YYYY-MM-DD.")
        if target < utcnow():
            raise HTTPException(400, "Target date cannot be in the past.")
    note = (body.note or "").strip()[:500] or f"Taken up by {c.department}."
    run_transition(db, c, user, "acknowledged", note=note, target_date=target)
    return services.cluster_detail(c, user)


@router.post("/issues/{cid}/progress")
def progress(cid: int, progress: int = Form(...), note: str = Form(""), photo: Optional[UploadFile] = File(None),
             user: User = Depends(official_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    ensure_department(user, c)
    if not 1 <= progress <= 99:
        raise HTTPException(400, "Progress must be between 1 and 99. Use 'Mark completed' to finish.")
    url = None
    if photo and photo.filename:
        s = save_upload(photo)
        if s["type"] != "image":
            raise HTTPException(400, "Progress photo must be an image.")
        url = s["url"]
    run_transition(db, c, user, "in_progress", note=(note or "").strip()[:500], progress=progress, photo_url=url)
    return services.cluster_detail(c, user)


@router.post("/issues/{cid}/complete")
def complete(cid: int, note: str = Form(""), photo: Optional[UploadFile] = File(None),
             user: User = Depends(official_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    ensure_department(user, c)
    if not (photo and photo.filename):
        raise HTTPException(400, "A photo of the completed work is mandatory.")
    s = save_upload(photo)
    if s["type"] != "image":
        raise HTTPException(400, "Completion proof must be an image.")
    run_transition(db, c, user, "completed", note=(note or "").strip()[:500] or "Work completed.", photo_url=s["url"])
    return services.cluster_detail(c, user)


@router.post("/issues/{cid}/override")
def override(cid: int, body: OverrideBody, user: User = Depends(official_only), db: Session = Depends(get_db)):
    c = get_cluster(db, cid)
    ensure_department(user, c)
    reason = (body.reason or "").strip()[:300]
    if len(reason) < 5:
        raise HTTPException(400, "Please give a short reason for the override (audit trail).")
    notes = []
    if body.category:
        if body.category not in ai_engine.TAXONOMY:
            raise HTTPException(400, "Unknown category.")
        subs = ai_engine.TAXONOMY[body.category]["subs"]
        sub = body.sub_category if body.sub_category in subs else next(iter(subs))
        c.category, c.sub_category = body.category, sub
        c.department = ai_engine.TAXONOMY[body.category]["department"]
        c.recategorised = True
        notes.append(f"re-categorised to {c.category} / {sub} (routed to {c.department})")
    if body.clear_priority:
        c.priority_override = None
        notes.append("priority override cleared")
    elif body.priority is not None:
        if not 0 <= body.priority <= 100:
            raise HTTPException(400, "Priority must be between 0 and 100.")
        c.priority_override = body.priority
        notes.append(f"priority set to {body.priority}")
    if not notes:
        raise HTTPException(400, "Nothing to override.")
    c.updated_at = utcnow()
    services.add_event(db, c, "note", user, f"Officer override: {'; '.join(notes)}. Reason: {reason}")
    db.commit()
    db.refresh(c)
    return services.cluster_detail(c, user)
