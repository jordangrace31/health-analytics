import pytest
from sqlalchemy.exc import IntegrityError
from app.models import User, DailySummary

def test_create_user_and_unique_username(db_session):
    db_session.add(User(username="jordan", password_hash="x"))
    db_session.commit()
    db_session.add(User(username="jordan", password_hash="y"))
    with pytest.raises(IntegrityError):
        db_session.commit()

def test_daily_summary_unique_per_metric_day(db_session):
    # A real User row is required here: app/db.py enables PRAGMA
    # foreign_keys=ON, and DailySummary.user_id is a ForeignKey("users.id").
    # Using a bare literal user_id (as in the task brief's sample) trips the
    # FK constraint on the first commit instead of exercising the unique
    # constraint under test, so we create a user first.
    user = User(username="dana", password_hash="x")
    db_session.add(user)
    db_session.commit()

    db_session.add(DailySummary(user_id=user.id, metric_key="steps", day="2026-01-01", value=100))
    db_session.commit()
    db_session.add(DailySummary(user_id=user.id, metric_key="steps", day="2026-01-01", value=200))
    with pytest.raises(IntegrityError):
        db_session.commit()
