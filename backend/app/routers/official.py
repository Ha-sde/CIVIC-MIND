from collections import Counter
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..ai_engine import DEPARTMENTS
from ..database import get_db
from ..models import Cluster, Complaint, User, utcnow
from ..security import official_only

router = APIRouter(prefix="/api/official", tags=["official"])


def scoped(db: Session, user: User, scope: str):
    q = db.query(Cluster)
    if scope != "all":
        q = q.filter(Cluster.department == user.department)
    return q


@router.get("/queue")
def queue(scope: str = "mine", stage: str = "open", q: str = "", sort: str = "priority",
          user: User = Depends(official_only), db: Session = Depends(get_db)):
    clusters = scoped(db, user, scope).all()
    stats = services.summarise(clusters)
    rows = clusters
    if stage == "open":
        rows = [c for c in rows if c.stage != "completed"]
    elif stage == "overdue":
        rows = [c for c in rows if services.is_overdue(c)]
    elif stage != "all":
        rows = [c for c in rows if c.stage == stage]
    if q.strip():
        needle = q.strip().lower()
        rows = [c for c in rows if needle in (c.title + " " + (c.address or "") + " " + c.sub_category + " " + c.category).lower()]
    cards = [services.cluster_card(c) for c in rows]
    keys = {
        "priority": lambda d: (-d["priority"]["score"], d["created_at"]),
        "newest": lambda d: d["created_at"],
        "oldest": lambda d: d["created_at"],
        "reports": lambda d: (-d["reports"], d["created_at"]),
    }
    cards.sort(key=keys.get(sort, keys["priority"]), reverse=(sort == "newest"))
    return {"stats": stats, "department": user.department, "items": cards}


@router.get("/analytics")
def analytics(user: User = Depends(official_only), db: Session = Depends(get_db)):
    clusters = db.query(Cluster).all()
    mine = [c for c in clusters if c.department == user.department]
    by_cat = Counter(c.sub_category for c in mine)
    by_stage = Counter(c.stage for c in mine)
    today = utcnow().date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    since = utcnow() - timedelta(days=14)
    per_day = Counter(r.created_at.date() for r in db.query(Complaint).filter(Complaint.created_at >= since).all())
    dept_perf = []
    for dep in DEPARTMENTS:
        s = services.summarise([c for c in clusters if c.department == dep])
        if s["total"]:
            dept_perf.append({"department": dep, **s})
    return {
        "department": user.department,
        "summary": services.summarise(mine),
        "by_category": [{"label": k, "count": v} for k, v in by_cat.most_common(8)],
        "by_stage": [{"label": services.STAGE_LABEL[k], "count": v} for k, v in by_stage.items()],
        "trend": [{"day": d.strftime("%d %b"), "count": per_day.get(d, 0)} for d in days],
        "departments": dept_perf,
    }
