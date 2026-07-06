from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models import DailySummary

METRIC_MAP = {
    "steps":          {"types": ["HKQuantityTypeIdentifierStepCount"], "agg": "SUM"},
    "distance":       {"types": ["HKQuantityTypeIdentifierDistanceWalkingRunning"], "agg": "SUM"},
    "active_energy":  {"types": ["HKQuantityTypeIdentifierActiveEnergyBurned"], "agg": "SUM"},
    "resting_hr":     {"types": ["HKQuantityTypeIdentifierRestingHeartRate"], "agg": "AVG"},
    "heart_rate_avg": {"types": ["HKQuantityTypeIdentifierHeartRate"], "agg": "AVG"},
}
SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"

def compute_daily_summaries(db: Session, user_id: int, import_id: int) -> int:
    db.query(DailySummary).filter(DailySummary.user_id == user_id).delete()
    inserted = 0
    for metric_key, cfg in METRIC_MAP.items():
        placeholders = ",".join(f":t{i}" for i in range(len(cfg["types"])))
        params = {"uid": user_id, "iid": import_id, "mk": metric_key}
        params.update({f"t{i}": t for i, t in enumerate(cfg["types"])})
        rows = db.execute(text(f"""
            SELECT date(start_time) AS day, {cfg['agg']}(value_num) AS v
            FROM health_records
            WHERE import_id = :iid AND value_num IS NOT NULL AND type IN ({placeholders})
            GROUP BY date(start_time)
            HAVING day IS NOT NULL
        """), params).all()
        for day, v in rows:
            db.add(DailySummary(user_id=user_id, metric_key=metric_key, day=day, value=v))
            inserted += 1
    # sleep: sum of asleep interval hours, bucketed by start day
    rows = db.execute(text("""
        SELECT date(start_time) AS day,
               SUM((julianday(end_time) - julianday(start_time)) * 24.0) AS hours
        FROM health_records
        WHERE import_id = :iid AND type = :st
          AND value_text LIKE 'HKCategoryValueSleepAnalysisAsleep%'
          AND end_time IS NOT NULL
        GROUP BY date(start_time)
        HAVING day IS NOT NULL
    """), {"iid": import_id, "st": SLEEP_TYPE}).all()
    for day, hours in rows:
        db.add(DailySummary(user_id=user_id, metric_key="sleep_hours", day=day, value=hours))
        inserted += 1
    return inserted
