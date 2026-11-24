"""Business logic: clustering, explainable priority engine, stage machine, serialisation, stats."""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import ai_engine
from .ai_engine import CATEGORY_WEIGHT, TAXONOMY, AIResult
from .config import settings
from .models import Cluster, Complaint, Notification, TimelineEvent, User, utcnow

STAGE_LABEL = {"received": "Received", "merged": "Report merged", "acknowledged": "Acknowledged",
               "in_progress": "In progress", "completed": "Completed", "reopened": "Reopened", "note": "Update"}
ALLOWED = {
    "received": {"acknowledged"},
    "acknowledged": {"in_progress"},
    "in_progress": {"in_progress", "completed"},
    "reopened": {"in_progress"},
    "completed": {"reopened"},
}


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


# ----------------------------------------------------------------------------- geo + text similarity
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_STOP = {"the", "and", "for", "are", "was", "has", "have", "this", "that", "with", "near", "from", "not", "there", "very",
         "our", "your", "you", "its", "been", "since", "but", "can", "any", "all", "one", "out", "got", "get", "please"}


def _tok(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w\u0900-\u097F]+", (text or "").lower()) if len(w) > 2 and w not in _STOP]


def cosine(a: str, b: str) -> float:
    ta, tb = Counter(_tok(a)), Counter(_tok(b))
    if not ta or not tb:
        return 0.0
    wa = {k: 1 + math.log(v) for k, v in ta.items()}
    wb = {k: 1 + math.log(v) for k, v in tb.items()}
    dot = sum(wa[k] * wb[k] for k in wa.keys() & wb.keys())
    na = math.sqrt(sum(v * v for v in wa.values()))
    nb = math.sqrt(sum(v * v for v in wb.values()))
    return dot / (na * nb) if na and nb else 0.0


def find_cluster(db: Session, category: str, lat: float, lon: float, text: str) -> Optional[Cluster]:
    """Same category + within radius (or within 2x radius with similar wording) + still open + recent."""
    radius = settings.CLUSTER_RADIUS_M
    dlat = (2 * radius) / 111320.0
    dlon = (2 * radius) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
    since = utcnow() - timedelta(days=settings.CLUSTER_WINDOW_DAYS)
    candidates = db.query(Cluster).filter(
        Cluster.category == category, Cluster.stage != "completed", Cluster.created_at >= since,
        Cluster.lat.between(lat - dlat, lat + dlat), Cluster.lon.between(lon - dlon, lon + dlon)).all()
    best, best_cost = None, None
    for c in candidates:
        dist = haversine_m(lat, lon, c.lat, c.lon)
        sim = cosine(text, c.corpus or "")
        if category == "Other" and sim < 0.30:
            continue
        if dist <= radius or (dist <= 2 * radius and sim >= 0.45):
            cost = dist - 120 * sim
            if best_cost is None or cost < best_cost:
                best, best_cost = c, cost
    return best


# ----------------------------------------------------------------------------- notifications / timeline
def add_event(db: Session, cluster: Cluster, stage: str, actor: Optional[User] = None, note: str = "",
              progress: Optional[int] = None, photo_url: Optional[str] = None) -> TimelineEvent:
    ev = TimelineEvent(cluster_id=cluster.id, stage=stage, actor_id=actor.id if actor else None,
                       actor_name=(actor.name if actor else "System"), note=note, progress=progress, photo_url=photo_url)
    db.add(ev)
    return ev


def notify_reporters(db: Session, cluster: Cluster, message: str, exclude_user_id: Optional[int] = None):
    user_ids = {uid for (uid,) in db.query(Complaint.user_id).filter(Complaint.cluster_id == cluster.id).distinct()}
    for uid in user_ids:
        if uid != exclude_user_id:
            db.add(Notification(user_id=uid, cluster_id=cluster.id, message=message[:300]))


# ----------------------------------------------------------------------------- ingestion
def ingest(db: Session, user: User, text: str, lat: float, lon: float, address: str, media: list,
           ai: AIResult) -> tuple[Complaint, Cluster, bool]:
    cluster = find_cluster(db, ai.category, lat, lon, text)
    merged = cluster is not None
    if merged:
        n = cluster.complaint_count
        cluster.lat = (cluster.lat * n + lat) / (n + 1)
        cluster.lon = (cluster.lon * n + lon) / (n + 1)
        cluster.complaint_count = n + 1
        cluster.severity = max(cluster.severity, ai.severity)
        cluster.vulnerability = bool(cluster.vulnerability or ai.vulnerability)
        cluster.corpus = ((cluster.corpus or "") + " " + text)[-3000:]
        cluster.updated_at = utcnow()
    else:
        cluster = Cluster(
            title=ai.title or ai.sub_category, category=ai.category, sub_category=ai.sub_category,
            department=ai.department, lat=lat, lon=lon, address=address or "", severity=ai.severity,
            confidence=ai.confidence, vulnerability=ai.vulnerability, ai_reason=ai.reason, ai_engine=ai.engine,
            corpus=text[-3000:], complaint_count=1, stage="received")
        db.add(cluster)
        db.flush()
        add_event(db, cluster, "received", None,
                  f"Complaint received and categorised as {ai.category} / {ai.sub_category}. Routed to {ai.department}.")
    complaint = Complaint(user_id=user.id, cluster_id=cluster.id, text=text, address=address or "", lat=lat, lon=lon,
                          media=media, severity=ai.severity, confidence=ai.confidence)
    db.add(complaint)
    if merged:
        add_event(db, cluster, "merged", None, f"Report #{cluster.complaint_count} merged into this issue (same place, same problem).")
    db.add(Notification(user_id=user.id, cluster_id=cluster.id,
                        message=("Your report was merged with an existing issue" if merged else "Your complaint was received")
                        + f" and routed to {cluster.department}."))
    db.flush()
    return complaint, cluster, merged


# ----------------------------------------------------------------------------- stage machine
def transition(db: Session, cluster: Cluster, actor: User, new_stage: str, note: str = "", progress: Optional[int] = None,
               photo_url: Optional[str] = None, target_date: Optional[datetime] = None, force: bool = False):
    if not force and new_stage not in ALLOWED.get(cluster.stage, set()):
        raise ValueError(f"Cannot move from '{STAGE_LABEL[cluster.stage]}' to '{STAGE_LABEL[new_stage]}'. Stages cannot be skipped.")
    now = utcnow()
    if new_stage == "acknowledged":
        cluster.acknowledged_at = now
        cluster.target_date = target_date
        msg = f"{cluster.department} has taken up your complaint" + (f" - target {target_date:%d %b %Y}." if target_date else ".")
    elif new_stage == "in_progress":
        cluster.progress = max(0, min(99, progress if progress is not None else cluster.progress))
        msg = f"Work is underway on your complaint - {cluster.progress}% complete."
    elif new_stage == "completed":
        if not photo_url and not force:
            raise ValueError("A photo of the completed work is mandatory to mark an issue resolved.")
        cluster.progress = 100
        cluster.resolved_at = now
        msg = "Your complaint is marked resolved. Please confirm whether the problem is really fixed."
    elif new_stage == "reopened":
        cluster.reopen_count += 1
        cluster.last_reopened_at = now
        cluster.progress = 0
        cluster.resolved_at = None
        msg = "An issue you reported was reopened."
    else:
        msg = "Your complaint was updated."
    cluster.stage = new_stage
    cluster.updated_at = now
    add_event(db, cluster, new_stage, actor, note, cluster.progress if new_stage in ("in_progress", "completed") else None, photo_url)
    notify_reporters(db, cluster, msg, exclude_user_id=actor.id if actor.role == "citizen" else None)


# ----------------------------------------------------------------------------- explainable priority engine
def compute_priority(c: Cluster, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    w = settings.WEIGHTS
    total_w = sum(w.values()) or 1.0
    end = c.resolved_at or now
    days_open = max(0.0, (end - c.created_at).total_seconds() / 86400)
    comps = [
        ("reports", "Reports merged", min(1.0, math.log(max(c.complaint_count, 1)) / math.log(25)), w["reports"]),
        ("severity", "Severity", (max(1, c.severity) - 1) / 4, w["severity"]),
        ("category", "Category importance", CATEGORY_WEIGHT.get(c.category, 0.5), w["category"]),
        ("age", "Time unresolved", min(1.0, days_open / 14), w["age"]),
        ("vulnerability", "Near school / hospital / transit", 1.0 if c.vulnerability else 0.0, w["vulnerability"]),
    ]
    breakdown = [{"key": k, "label": lbl, "value": round(v, 2), "weight": round(wt / total_w, 2),
                  "points": round(100 * v * wt / total_w, 1)} for k, lbl, v, wt in comps]
    computed = round(sum(b["points"] for b in breakdown))
    overridden = c.priority_override is not None
    score = int(c.priority_override) if overridden else computed
    label = "critical" if score >= 75 else "high" if score >= 55 else "medium" if score >= 35 else "low"
    return {"score": score, "computed": computed, "overridden": overridden, "label": label, "breakdown": breakdown}


def is_overdue(c: Cluster, now: Optional[datetime] = None) -> bool:
    now = now or utcnow()
    if c.stage == "completed":
        return False
    sla = timedelta(hours=settings.ACK_SLA_HOURS)
    if c.stage == "received" and now - c.created_at > sla:
        return True
    if c.stage == "reopened" and c.last_reopened_at and now - c.last_reopened_at > sla:
        return True
    return bool(c.target_date and now > c.target_date)


# ----------------------------------------------------------------------------- serialisation
def cluster_card(c: Cluster) -> dict:
    now = utcnow()
    first_img = None
    for comp in c.complaints:
        for m in comp.media or []:
            if m.get("type") == "image":
                first_img = m["url"]
                break
        if first_img:
            break
    return {
        "id": c.id, "title": c.title, "category": c.category, "sub_category": c.sub_category, "department": c.department,
        "address": c.address, "lat": c.lat, "lon": c.lon, "severity": c.severity, "reports": c.complaint_count,
        "stage": c.stage, "stage_label": STAGE_LABEL[c.stage], "progress": c.progress, "image": first_img,
        "priority": compute_priority(c, now), "overdue": is_overdue(c, now), "reopen_count": c.reopen_count,
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "acknowledged_at": iso(c.acknowledged_at),
        "resolved_at": iso(c.resolved_at), "target_date": iso(c.target_date),
    }


def event_dict(e: TimelineEvent) -> dict:
    return {"id": e.id, "stage": e.stage, "label": STAGE_LABEL.get(e.stage, e.stage), "actor": e.actor_name, "note": e.note,
            "progress": e.progress, "photo": e.photo_url, "at": iso(e.created_at)}


def cluster_detail(c: Cluster, viewer: Optional[User]) -> dict:
    d = cluster_card(c)
    d["timeline"] = [event_dict(e) for e in c.events]
    d["media"] = [m for comp in c.complaints for m in (comp.media or [])]
    d["confirmations"] = c.confirmations
    d["ai"] = {"engine": c.ai_engine, "confidence": c.confidence, "reason": c.ai_reason,
               "needs_review": c.confidence < 0.5, "vulnerability": bool(c.vulnerability), "recategorised": c.recategorised}
    d["can_reopen_until"] = iso(c.resolved_at + timedelta(days=settings.REOPEN_WINDOW_DAYS)) if c.resolved_at else None
    mine = [comp for comp in c.complaints if viewer and comp.user_id == viewer.id]
    d["my_reports"] = [{"id": m.id, "text": m.text, "created_at": iso(m.created_at), "media": m.media or []} for m in mine]
    d["is_reporter"] = bool(mine)
    d["can_act"] = bool(viewer and viewer.role == "official" and viewer.department == c.department)
    if viewer and viewer.role == "official":
        d["reporters"] = [{"id": comp.id, "name": comp.user.name, "contact": comp.user.contact, "text": comp.text,
                           "created_at": iso(comp.created_at), "severity": comp.severity} for comp in c.complaints]
    return d


# ----------------------------------------------------------------------------- stats
def _avg(values):
    return round(sum(values) / len(values), 1) if values else None


def summarise(clusters: list[Cluster]) -> dict:
    now = utcnow()
    open_ = [c for c in clusters if c.stage != "completed"]
    ack_h = [(c.acknowledged_at - c.created_at).total_seconds() / 3600 for c in clusters if c.acknowledged_at]
    res_d = [(c.resolved_at - c.created_at).total_seconds() / 86400 for c in clusters if c.resolved_at]
    ever_done = [c for c in clusters if c.resolved_at or c.reopen_count]
    reopened = [c for c in ever_done if c.reopen_count]
    return {
        "total": len(clusters), "open": len(open_), "resolved": len(clusters) - len(open_),
        "overdue": sum(1 for c in open_ if is_overdue(c, now)),
        "reports": sum(c.complaint_count for c in clusters),
        "avg_ack_hours": _avg(ack_h), "avg_resolve_days": _avg(res_d),
        "reopen_rate": round(100 * len(reopened) / len(ever_done)) if ever_done else 0,
    }
