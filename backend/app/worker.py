import os
from datetime import datetime, timezone
from app.db import SessionLocal
from app.models import Import, HealthRecord, Workout
from app.parser import open_export, iter_elements
from app.aggregation import compute_daily_summaries

BATCH = 5000

def run_import(import_id: int, file_path: str) -> None:
    db = SessionLocal()
    try:
        imp = db.get(Import, import_id)
        imp.status = "processing"
        db.commit()
        user_id = imp.user_id

        record_batch: list[dict] = []
        workout_batch: list[dict] = []
        count = 0

        def flush_records():
            if record_batch:
                db.bulk_insert_mappings(HealthRecord, record_batch)
                record_batch.clear()

        def flush_workouts():
            if workout_batch:
                db.bulk_insert_mappings(Workout, workout_batch)
                workout_batch.clear()

        with open_export(file_path) as fh:
            for kind, d in iter_elements(fh):
                d = {**d, "user_id": user_id, "import_id": import_id}
                if kind == "record":
                    record_batch.append(d)
                    count += 1
                    if len(record_batch) >= BATCH:
                        flush_records()
                else:
                    workout_batch.append(d)
                    if len(workout_batch) >= BATCH:
                        flush_workouts()
        flush_records()
        flush_workouts()

        compute_daily_summaries(db, user_id, import_id)

        # transactional swap: drop everything from earlier imports for this user
        db.query(HealthRecord).filter(
            HealthRecord.user_id == user_id, HealthRecord.import_id != import_id).delete()
        db.query(Workout).filter(
            Workout.user_id == user_id, Workout.import_id != import_id).delete()
        db.query(Import).filter(
            Import.user_id == user_id, Import.id != import_id,
            Import.status == "complete").update({"status": "superseded"})

        imp.record_count = count
        imp.status = "complete"
        imp.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        imp = db.get(Import, import_id)
        if imp:
            imp.status = "failed"
            imp.error_message = str(exc)[:500]
            db.commit()
    finally:
        db.close()
        if os.path.exists(file_path):
            os.remove(file_path)
