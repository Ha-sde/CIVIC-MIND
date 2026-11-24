from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..ai_engine import DEPARTMENTS, TAXONOMY
from ..config import settings
from ..database import get_db
from ..models import Cluster

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/config")
def config():
    lat, lon = (float(x) for x in settings.MAP_DEFAULT.split(","))
    return {"app": settings.APP_NAME, "otp_mode": settings.OTP_MODE,
            "demo_otp": settings.DEMO_OTP if settings.OTP_MODE == "demo" else None,
            "invite_required": bool(settings.OFFICIAL_INVITE_CODE), "map_center": [lat, lon],
            "ai": "claude+local" if settings.ANTHROPIC_API_KEY else "local",
            "ack_sla_hours": settings.ACK_SLA_HOURS, "reopen_days": settings.REOPEN_WINDOW_DAYS,
            "max_files": settings.MAX_FILES, "max_mb": settings.MAX_UPLOAD_MB}


@router.get("/taxonomy")
def taxonomy():
    return {"departments": DEPARTMENTS,
            "categories": {c: {"department": v["department"], "subs": list(v["subs"].keys())} for c, v in TAXONOMY.items()}}


@router.get("/public/weights")
def weights():
    total = sum(settings.WEIGHTS.values()) or 1
    return {k: round(v / total, 2) for k, v in settings.WEIGHTS.items()}


@router.get("/public/stats")
def public_stats(db: Session = Depends(get_db)):
    clusters = db.query(Cluster).all()
    out = services.summarise(clusters)
    out["departments"] = [{"department": d, **services.summarise([c for c in clusters if c.department == d])} for d in DEPARTMENTS
                          if any(c.department == d for c in clusters)]
    return out


@router.get("/public/issues")
def public_issues(department: str = "", status: str = "all", q: str = "", limit: int = 60, db: Session = Depends(get_db)):
    query = db.query(Cluster)
    if department:
        query = query.filter(Cluster.department == department)
    rows = query.all()
    if status == "open":
        rows = [c for c in rows if c.stage != "completed"]
    elif status == "resolved":
        rows = [c for c in rows if c.stage == "completed"]
    if q.strip():
        needle = q.strip().lower()
        rows = [c for c in rows if needle in (c.title + " " + (c.address or "") + " " + c.sub_category).lower()]
    cards = [services.cluster_card(c) for c in rows]
    cards.sort(key=lambda d: (d["stage"] == "completed", -d["priority"]["score"]))
    return cards[: max(1, min(limit, 200))]
