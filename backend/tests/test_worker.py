import importlib
import os
from app.models import User, Import, HealthRecord, Workout, DailySummary

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")

def _new_import(db, user_id):
    imp = Import(user_id=user_id, filename="export.xml", status="pending")
    db.add(imp); db.commit(); db.refresh(imp)
    return imp.id

def _fresh_run_import():
    # app.worker binds `SessionLocal` from `app.db` at import time (it opens
    # its own session rather than using the request-scoped get_db). The
    # temp_db fixture reloads app.db per test with a fresh engine/tmp_path,
    # so app.worker must be reloaded too or it keeps using a stale
    # SessionLocal bound to a previous (or the real, non-test) database.
    import app.worker
    importlib.reload(app.worker)
    return app.worker.run_import

def test_run_import_success(temp_db):
    run_import = _fresh_run_import()
    with temp_db.SessionLocal() as db:
        db.add(User(id=1, username="jo", password_hash="x")); db.commit()
        iid = _new_import(db, 1)
    # copy fixture to a temp path the worker will delete
    tmp = FIX + ".copy.xml"
    with open(FIX, "rb") as s, open(tmp, "wb") as d:
        d.write(s.read())
    run_import(iid, tmp)
    with temp_db.SessionLocal() as db:
        imp = db.get(Import, iid)
        assert imp.status == "complete"
        assert imp.record_count == 7
        assert imp.export_date == "2026-07-01 09:00:00"
        assert db.query(Workout).count() == 1
        steps = db.query(DailySummary).filter_by(metric_key="steps", day="2026-06-01").one()
        assert steps.value == 1200
    assert not os.path.exists(tmp)  # temp file cleaned up

def test_reimport_replaces_previous(temp_db):
    run_import = _fresh_run_import()
    with temp_db.SessionLocal() as db:
        db.add(User(id=1, username="jo", password_hash="x")); db.commit()
        i1 = _new_import(db, 1)
    tmp1 = FIX + ".a.xml"; open(tmp1, "wb").write(open(FIX, "rb").read())
    run_import(i1, tmp1)
    with temp_db.SessionLocal() as db:
        i2 = _new_import(db, 1)
    tmp2 = FIX + ".b.xml"; open(tmp2, "wb").write(open(FIX, "rb").read())
    run_import(i2, tmp2)
    with temp_db.SessionLocal() as db:
        # only the second import's records remain
        assert db.query(HealthRecord).filter(HealthRecord.import_id == i1).count() == 0
        assert db.query(HealthRecord).filter(HealthRecord.import_id == i2).count() == 7
        # the prior import's workouts and daily summaries are gone too
        assert db.query(Workout).filter(Workout.import_id == i1).count() == 0
        assert db.query(Workout).filter(Workout.import_id == i2).count() == 1
        # daily_summaries are rebuilt for the newest import only
        assert db.query(DailySummary).filter_by(user_id=1).count() > 0
        # (DailySummary has no import_id; assert the total matches a single
        # import's worth by re-running would be circular — instead assert the
        # steps day value reflects the second import, i.e. 1200, not doubled.)
        assert db.query(DailySummary).filter_by(
            metric_key="steps", day="2026-06-01").one().value == 1200

def test_mid_stream_failure_no_orphans_and_prior_intact(temp_db):
    import app.worker
    worker = importlib.reload(app.worker)
    # seed a user and a PRIOR complete import with real data to protect
    with temp_db.SessionLocal() as db:
        db.add(User(id=1, username="jo", password_hash="x")); db.commit()
        i1 = _new_import(db, 1)
    tmp1 = FIX + ".prior.xml"
    with open(FIX, "rb") as s, open(tmp1, "wb") as d:
        d.write(s.read())
    worker.run_import(i1, tmp1)
    with temp_db.SessionLocal() as db:
        prior_records = db.query(HealthRecord).filter(HealthRecord.import_id == i1).count()
        prior_workouts = db.query(Workout).filter(Workout.import_id == i1).count()
        prior_summaries = db.query(DailySummary).filter_by(user_id=1).count()
        assert prior_records == 7 and prior_workouts == 1 and prior_summaries > 0
        i2 = _new_import(db, 1)

    # force an exception AFTER the record/workout inserts (during aggregation)
    def boom(*args, **kwargs):
        raise RuntimeError("aggregation blew up mid-import")
    worker.compute_daily_summaries = boom

    tmp2 = FIX + ".bad.xml"
    with open(FIX, "rb") as s, open(tmp2, "wb") as d:
        d.write(s.read())
    worker.run_import(i2, tmp2)

    with temp_db.SessionLocal() as db:
        imp = db.get(Import, i2)
        # (a) failed with a message
        assert imp.status == "failed"
        assert imp.error_message
        # (b) NO orphaned rows for the failed import
        assert db.query(HealthRecord).filter(HealthRecord.import_id == i2).count() == 0
        assert db.query(Workout).filter(Workout.import_id == i2).count() == 0
        # (c) the prior import's data is fully intact
        assert db.query(HealthRecord).filter(HealthRecord.import_id == i1).count() == prior_records
        assert db.query(Workout).filter(Workout.import_id == i1).count() == prior_workouts
        assert db.query(DailySummary).filter_by(user_id=1).count() == prior_summaries
        assert db.get(Import, i1).status == "complete"
    assert not os.path.exists(tmp2)  # temp file cleaned up even on failure

def test_failed_import_marks_failed(temp_db):
    run_import = _fresh_run_import()
    with temp_db.SessionLocal() as db:
        db.add(User(id=1, username="jo", password_hash="x")); db.commit()
        iid = _new_import(db, 1)
    run_import(iid, "/does/not/exist.xml")
    with temp_db.SessionLocal() as db:
        assert db.get(Import, iid).status == "failed"
        assert db.get(Import, iid).error_message
