from app.models import User, Import, HealthRecord, DailySummary
from app.aggregation import compute_daily_summaries

def _add(db, **kw):
    db.add(HealthRecord(user_id=1, import_id=1, source_name="w", **kw))

def test_compute_summaries(db_session):
    # FK enforcement (PRAGMA foreign_keys=ON) requires parent rows before
    # inserting HealthRecord/DailySummary rows that reference users.id and
    # imports.id. Seed a User(id=1) and Import(id=1) first. These models have
    # no relationship() mappings, so SQLAlchemy's unit-of-work does not infer
    # FK insert ordering across a single flush -- commit User before Import
    # so the parent row exists when Import's FK is checked.
    db_session.add(User(id=1, username="jo", password_hash="x"))
    db_session.commit()
    db_session.add(Import(id=1, user_id=1, filename="e", status="processing"))
    db_session.commit()

    # steps: two on day 1 -> sum 1200
    _add(db_session, type="HKQuantityTypeIdentifierStepCount", unit="count", value_num=500, start_time="2026-06-01 08:00:00")
    _add(db_session, type="HKQuantityTypeIdentifierStepCount", unit="count", value_num=700, start_time="2026-06-01 09:00:00")
    # resting hr: 60 & 70 -> avg 65
    _add(db_session, type="HKQuantityTypeIdentifierRestingHeartRate", value_num=60, start_time="2026-06-01 07:00:00")
    _add(db_session, type="HKQuantityTypeIdentifierRestingHeartRate", value_num=70, start_time="2026-06-01 20:00:00")
    # sleep: 7h asleep on the start day
    _add(db_session, type="HKCategoryTypeIdentifierSleepAnalysis", value_text="HKCategoryValueSleepAnalysisAsleepCore",
         start_time="2026-06-01 23:00:00", end_time="2026-06-02 06:00:00")
    # in-bed should be excluded
    _add(db_session, type="HKCategoryTypeIdentifierSleepAnalysis", value_text="HKCategoryValueSleepAnalysisInBed",
         start_time="2026-06-01 22:30:00", end_time="2026-06-01 23:00:00")
    db_session.commit()

    n = compute_daily_summaries(db_session, user_id=1, import_id=1)
    db_session.commit()
    assert n >= 3
    def val(mk):
        return db_session.query(DailySummary).filter_by(user_id=1, metric_key=mk, day="2026-06-01").one().value
    assert val("steps") == 1200
    assert val("resting_hr") == 65
    assert round(val("sleep_hours"), 2) == 7.0
