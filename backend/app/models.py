from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

class Import(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|processing|complete|failed
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    export_date: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class HealthRecord(Base):
    __tablename__ = "health_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    source_name: Mapped[str | None] = mapped_column(String, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(String, nullable=True)
    start_time: Mapped[str] = mapped_column(String)
    end_time: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (Index("ix_records_user_type_start", "user_id", "type", "start_time"),)

class Workout(Base):
    __tablename__ = "workouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"), index=True)
    activity_type: Mapped[str] = mapped_column(String)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    start_time: Mapped[str] = mapped_column(String)
    end_time: Mapped[str | None] = mapped_column(String, nullable=True)

class DailySummary(Base):
    __tablename__ = "daily_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    metric_key: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String)  # YYYY-MM-DD
    value: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("user_id", "metric_key", "day", name="uq_user_metric_day"),)
