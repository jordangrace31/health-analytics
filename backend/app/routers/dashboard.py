from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import DailySummary, Workout, User
from app.security import get_current_user
from app.aggregation import METRIC_MAP

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
ALL_METRICS = list(METRIC_MAP.keys()) + ["sleep_hours"]
RANGES = {"30d": 30, "90d": 90, "1y": 365, "all": None}

@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = []
    for mk in ALL_METRICS:
        rows = (db.query(DailySummary)
                .filter(DailySummary.user_id == user.id, DailySummary.metric_key == mk)
                .order_by(DailySummary.day.desc()).limit(2).all())
        if not rows:
            continue
        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        change = None
        if prev and prev.value:
            change = round((latest.value - prev.value) / prev.value * 100, 1)
        out.append({
            "metric_key": mk, "latest_value": latest.value, "latest_day": latest.day,
            "prev_value": prev.value if prev else None, "change_pct": change,
        })
    return {"metrics": out}

@router.get("/metrics/{metric_key}")
def metric_series(metric_key: str, range: str = "90d",
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if metric_key not in ALL_METRICS:
        raise HTTPException(status_code=400, detail="Unknown metric")
    if range not in RANGES:
        raise HTTPException(status_code=400, detail="Unknown range")
    q = db.query(DailySummary).filter(
        DailySummary.user_id == user.id, DailySummary.metric_key == metric_key)
    days = RANGES[range]
    if days is not None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        q = q.filter(DailySummary.day >= cutoff)
    rows = q.order_by(DailySummary.day.asc()).all()
    return {"metric_key": metric_key, "points": [{"day": r.day, "value": r.value} for r in rows]}

@router.get("/records")
def records(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    highlights = []
    top_steps = (db.query(DailySummary)
                 .filter(DailySummary.user_id == user.id, DailySummary.metric_key == "steps")
                 .order_by(DailySummary.value.desc()).first())
    if top_steps:
        highlights.append({"label": "Most steps in a day",
                           "value": top_steps.value, "day": top_steps.day})
    longest = (db.query(Workout).filter(Workout.user_id == user.id)
               .order_by(Workout.duration_sec.desc()).first())
    if longest and longest.duration_sec:
        highlights.append({"label": "Longest workout (min)",
                           "value": round(longest.duration_sec / 60, 1),
                           "day": (longest.start_time or "")[:10]})
    return {"highlights": highlights}
