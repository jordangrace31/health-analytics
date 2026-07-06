import os
from app.parser import norm_ts, to_float, open_export, iter_elements

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")

def test_norm_ts_and_to_float():
    assert norm_ts("2026-06-01 08:00:00 -0700") == "2026-06-01 08:00:00"
    assert norm_ts("") is None
    assert to_float("500") == 500.0
    assert to_float("not-a-number") is None

def test_iter_elements_records_and_workout():
    with open_export(FIX) as fh:
        items = list(iter_elements(fh))
    records = [d for kind, d in items if kind == "record"]
    workouts = [d for kind, d in items if kind == "workout"]
    assert len(records) == 7
    assert len(workouts) == 1
    steps = [r for r in records if r["type"].endswith("StepCount")]
    assert steps[0]["value_num"] == 500.0
    # malformed row still yielded, but with None value/ts
    bad = [r for r in steps if r["value_num"] is None][0]
    assert bad["start_time"] == "bad-date"[:19] or bad["start_time"] == "bad-date"
    assert workouts[0]["activity_type"] == "HKWorkoutActivityTypeRunning"
    assert workouts[0]["duration_sec"] == 1800.0
    assert workouts[0]["energy_kcal"] == 250.0

def test_iter_elements_export_date():
    with open_export(FIX) as fh:
        items = list(iter_elements(fh))
    export_dates = [d for kind, d in items if kind == "export_date"]
    records = [d for kind, d in items if kind == "record"]
    workouts = [d for kind, d in items if kind == "workout"]
    assert len(export_dates) == 1
    assert export_dates[0]["value"] == "2026-07-01 09:00:00"
    # adding ExportDate must not change record/workout counts
    assert len(records) == 7
    assert len(workouts) == 1
