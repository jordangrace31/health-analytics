# Apple Health Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted web app where 2 private users each upload their Apple Health `export.xml`, and view a personal summary dashboard.

**Architecture:** A FastAPI backend parses uploaded exports with a streaming XML reader, stores raw records in SQLite, and pre-aggregates daily summaries via SQL. The same backend serves a static React/TypeScript dashboard. Runs free on the owner's laptop; reachable remotely via Cloudflare Tunnel.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite (WAL), passlib[argon2], lxml, uvicorn (backend); React + TypeScript + Vite + React Router + Recharts (frontend); Docker Compose + cloudflared (deploy).

## Global Constraints

- Python **3.12**; Node **20+**.
- Database is **SQLite**, single file, **WAL mode** enabled. Access via **SQLAlchemy**; schema via **Alembic**.
- Every table has a `user_id` column; **every query filters by the logged-in `user_id`**. A user must never be able to read another user's data.
- Passwords hashed with **argon2** (`passlib`). Sessions via **signed, httpOnly, SameSite cookies**.
- XML parsing must be **streaming** (`lxml.iterparse` with element clearing) — must not load the whole file into memory.
- Re-import is a **full-snapshot replace**: a successful import atomically becomes the user's only dataset; on failure, prior data is untouched.
- Timestamps from Apple exports are stored as local wall-clock ISO strings `YYYY-MM-DD HH:MM:SS` (first 19 chars of the export value) so SQLite `date()`/`julianday()` work directly.
- TDD throughout: write the failing test, see it fail, implement, see it pass, commit.

**Metric aggregation map** (used by aggregation + dashboard):

| metric_key       | record type(s)                                    | daily aggregation |
|------------------|---------------------------------------------------|-------------------|
| `steps`          | `HKQuantityTypeIdentifierStepCount`               | SUM               |
| `distance`       | `HKQuantityTypeIdentifierDistanceWalkingRunning`  | SUM               |
| `active_energy`  | `HKQuantityTypeIdentifierActiveEnergyBurned`      | SUM               |
| `resting_hr`     | `HKQuantityTypeIdentifierRestingHeartRate`        | AVG               |
| `heart_rate_avg` | `HKQuantityTypeIdentifierHeartRate`               | AVG               |
| `sleep_hours`    | `HKCategoryTypeIdentifierSleepAnalysis` (asleep)  | SUM of interval hours |

---

## File Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app assembly, middleware, static serving
│   ├── config.py          # Settings from env
│   ├── db.py              # engine, SessionLocal, Base, get_db
│   ├── models.py          # SQLAlchemy models
│   ├── security.py        # password hashing, current-user dependency, rate limiter
│   ├── parser.py          # streaming Apple Health XML parser (+ zip support)
│   ├── aggregation.py     # METRIC_MAP + compute_daily_summaries
│   ├── worker.py          # run_import orchestration
│   └── routers/
│       ├── __init__.py
│       ├── auth.py        # /api/auth/*
│       ├── imports.py     # /api/imports*
│       └── dashboard.py   # /api/dashboard/*
├── migrations/            # Alembic
├── tests/
│   ├── conftest.py
│   ├── fixtures/sample_export.xml
│   ├── test_parser.py
│   ├── test_aggregation.py
│   ├── test_worker.py
│   ├── test_auth.py
│   ├── test_imports.py
│   └── test_dashboard.py
├── alembic.ini
└── pyproject.toml

frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/client.ts
│   ├── auth/AuthContext.tsx
│   ├── pages/{Login,Register,Dashboard,Import}.tsx
│   ├── components/{StatTile,TrendCard,Highlights,ProtectedRoute}.tsx
│   └── test/*.test.tsx
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts

docker-compose.yml
Dockerfile
.env.example
README.md
```

---

## Phase 1 — Backend Foundation

### Task 1: Backend scaffold

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/tests/__init__.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main:app` (FastAPI instance); `GET /api/health` → `{"status": "ok"}`. `app.config:get_settings()` → `Settings` with `database_url: str`, `session_secret: str`, `max_upload_mb: int`.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "health-analytics-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "passlib[argon2]>=1.7",
    "python-multipart>=0.0.9",
    "lxml>=5.2",
    "pandas>=2.2",
    "itsdangerous>=2.2",
    "pydantic-settings>=2.3",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_health.py`

```python
from fastapi.testclient import TestClient
from app.main import app

def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 4: Write `backend/app/__init__.py`** (empty) and `backend/app/config.py`

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/health.db"
    session_secret: str = "dev-insecure-change-me"
    max_upload_mb: int = 500
    cookie_secure: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Write `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Health Analytics")

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/
git commit -m "Add backend scaffold with health endpoint"
```

---

### Task 2: Database setup

**Files:**
- Create: `backend/app/db.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `app.db:Base` (DeclarativeBase), `app.db:engine`, `app.db:SessionLocal`, `app.db:get_db()` (FastAPI dependency yielding a `Session`), `app.db:init_db()` (creates tables + sets WAL).
- `conftest.py` produces the `db_session` and `client` pytest fixtures backed by a temp SQLite file.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_db.py`

```python
from sqlalchemy import text
from app.db import SessionLocal, init_db

def test_wal_mode_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    from app.config import get_settings
    get_settings.cache_clear()
    init_db()
    with SessionLocal() as s:
        mode = s.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Write `backend/app/db.py`**

```python
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings

class Base(DeclarativeBase):
    pass

settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    import app.models  # noqa: F401  ensure models are registered
    import os
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 4: Write `backend/tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'test.db'}")
    from app.config import get_settings
    get_settings.cache_clear()
    import importlib, app.db, app.models
    importlib.reload(app.db)
    importlib.reload(app.models)
    app.db.init_db()
    return app.db

@pytest.fixture()
def db_session(temp_db):
    with temp_db.SessionLocal() as s:
        yield s

@pytest.fixture()
def client(temp_db):
    import importlib, app.main
    importlib.reload(app.main)
    return TestClient(app.main.app)
```

> Note: `test_db.py` above uses its own inline setup; the shared fixtures here are for later tasks.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/tests/conftest.py backend/tests/test_db.py
git commit -m "Add SQLite engine with WAL mode and test fixtures"
```

---

### Task 3: Data models

**Files:**
- Create: `backend/app/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces SQLAlchemy models with these exact attributes:
  - `User(id, username, password_hash, created_at)`
  - `Import(id, user_id, filename, status, error_message, record_count, export_date, created_at, completed_at)`
  - `HealthRecord(id, user_id, import_id, type, source_name, unit, value_num, value_text, start_time, end_time)`
  - `Workout(id, user_id, import_id, activity_type, duration_sec, energy_kcal, distance, unit, start_time, end_time)`
  - `DailySummary(id, user_id, metric_key, day, value)` with unique `(user_id, metric_key, day)`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_models.py`

```python
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
    db_session.add(DailySummary(user_id=1, metric_key="steps", day="2026-01-01", value=100))
    db_session.commit()
    db_session.add(DailySummary(user_id=1, metric_key="steps", day="2026-01-01", value=200))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`.

- [ ] **Step 3: Write `backend/app/models.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Initialize Alembic and autogenerate the first migration**

Run:
```bash
cd backend && alembic init migrations
```
Then edit `migrations/env.py`: set `target_metadata` and URL from settings:
```python
from app.db import Base
from app.config import get_settings
import app.models  # noqa
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)
```
Generate + apply:
```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
Expected: a migration file appears under `migrations/versions/` and applies cleanly.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py backend/alembic.ini backend/migrations/
git commit -m "Add data models and initial Alembic migration"
```

---

## Phase 2 — Auth

### Task 4: Authentication

**Files:**
- Create: `backend/app/security.py`, `backend/app/routers/__init__.py`, `backend/app/routers/auth.py`
- Modify: `backend/app/main.py` (add SessionMiddleware + include router)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `security.hash_password(pw)->str`, `security.verify_password(pw, h)->bool`, `security.get_current_user(request, db)->User` (401 if unauthenticated), `security.login_rate_limit(request)` dependency.
- Endpoints: `POST /api/auth/register {username,password}`; `POST /api/auth/login {username,password}` (sets session cookie); `POST /api/auth/logout`; `GET /api/auth/me`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_auth.py`

```python
def test_register_login_me_logout(client):
    assert client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"}).status_code == 201
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "jo", "password": "pw12345"}).status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "jo"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

def test_login_wrong_password_generic_error(client):
    client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    r = client.post("/api/auth/login", json={"username": "jo", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials"

def test_duplicate_username_rejected(client):
    client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    r = client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    assert r.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — 404s / missing module.

- [ ] **Step 3: Write `backend/app/security.py`**

```python
import time
from collections import defaultdict
from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(pw: str) -> str:
    return _pwd.hash(pw)

def verify_password(pw: str, h: str) -> bool:
    return _pwd.verify(pw, h)

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

_attempts: dict[str, list[float]] = defaultdict(list)

def login_rate_limit(request: Request):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    window = [t for t in _attempts[ip] if now - t < 60]
    if len(window) >= 10:
        raise HTTPException(status_code=429, detail="Too many attempts")
    window.append(now)
    _attempts[ip] = window
```

- [ ] **Step 4: Write `backend/app/routers/__init__.py`** (empty) and `backend/app/routers/auth.py`

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.security import hash_password, verify_password, get_current_user, login_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])

class Credentials(BaseModel):
    username: constr(min_length=1, max_length=50)
    password: constr(min_length=6, max_length=200)

@router.post("/register", status_code=201)
def register(body: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username taken")
    db.add(User(username=body.username, password_hash=hash_password(body.password)))
    db.commit()
    return {"status": "created"}

@router.post("/login")
def login(body: Credentials, request: Request, db: Session = Depends(get_db),
          _: None = Depends(login_rate_limit)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user_id"] = user.id
    return {"status": "ok", "username": user.username}

@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}
```

- [ ] **Step 5: Modify `backend/app/main.py`** to add middleware + router + startup

```python
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.db import init_db
from app.routers import auth

settings = get_settings()
app = FastAPI(title="Health Analytics")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.cookie_secure,
    same_site="lax",
)

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/api/health")
def health():
    return {"status": "ok"}

app.include_router(auth.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (all three).

- [ ] **Step 7: Commit**

```bash
git add backend/app/security.py backend/app/routers/ backend/app/main.py backend/tests/test_auth.py
git commit -m "Add username/password auth with sessions and rate limiting"
```

---

## Phase 3 — Import Pipeline

### Task 5: Streaming XML parser

**Files:**
- Create: `backend/app/parser.py`, `backend/tests/fixtures/sample_export.xml`
- Test: `backend/tests/test_parser.py`

**Interfaces:**
- Produces:
  - `parser.norm_ts(value: str) -> str | None` — first 19 chars `YYYY-MM-DD HH:MM:SS`, or None if empty.
  - `parser.to_float(value: str) -> float | None`.
  - `parser.open_export(path: str) -> BinaryIO` — returns a file object for the XML, transparently extracting `export.xml` if `path` is a `.zip`.
  - `parser.iter_elements(fileobj) -> Iterator[tuple[str, dict]]` — yields `("record", {type, source_name, unit, value_num, value_text, start_time, end_time})` and `("workout", {activity_type, duration_sec, energy_kcal, distance, unit, start_time, end_time})`, clearing elements as it streams.

- [ ] **Step 1: Write `backend/tests/fixtures/sample_export.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <ExportDate value="2026-07-01 09:00:00 -0700"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="2026-06-01 08:00:00 -0700" endDate="2026-06-01 08:10:00 -0700" value="500"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="2026-06-01 09:00:00 -0700" endDate="2026-06-01 09:10:00 -0700" value="700"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Watch" unit="count/min" startDate="2026-06-01 07:00:00 -0700" endDate="2026-06-01 07:00:00 -0700" value="60"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Watch" unit="count/min" startDate="2026-06-01 20:00:00 -0700" endDate="2026-06-01 20:00:00 -0700" value="70"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-06-01 23:00:00 -0700" endDate="2026-06-02 06:00:00 -0700" value="HKCategoryValueSleepAnalysisAsleepCore"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-06-01 22:30:00 -0700" endDate="2026-06-01 23:00:00 -0700" value="HKCategoryValueSleepAnalysisInBed"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="bad-date" endDate="" value="not-a-number"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" totalEnergyBurned="250" totalEnergyBurnedUnit="kcal" totalDistance="5" totalDistanceUnit="km" startDate="2026-06-01 18:00:00 -0700" endDate="2026-06-01 18:30:00 -0700"/>
</HealthData>
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_parser.py`

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.parser'`.

- [ ] **Step 4: Write `backend/app/parser.py`**

```python
import zipfile
from typing import BinaryIO, Iterator
from lxml import etree

def norm_ts(value: str | None) -> str | None:
    if not value:
        return None
    return value[:19]

def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def open_export(path: str) -> BinaryIO:
    if path.lower().endswith(".zip"):
        zf = zipfile.ZipFile(path)
        name = next((n for n in zf.namelist() if n.endswith("export.xml")), None)
        if name is None:
            zf.close()
            raise ValueError("No export.xml found in zip")
        return zf.open(name)
    return open(path, "rb")

def _minutes_to_seconds(v: str | None, unit: str | None) -> float | None:
    n = to_float(v)
    if n is None:
        return None
    return n * 60.0 if (unit or "min").startswith("min") else n

def iter_elements(fileobj: BinaryIO) -> Iterator[tuple[str, dict]]:
    context = etree.iterparse(fileobj, events=("end",), tag=("Record", "Workout"))
    for _, el in context:
        if el.tag == "Record":
            v = el.get("value")
            yield ("record", {
                "type": el.get("type"),
                "source_name": el.get("sourceName"),
                "unit": el.get("unit"),
                "value_num": to_float(v),
                "value_text": v if to_float(v) is None else None,
                "start_time": norm_ts(el.get("startDate")),
                "end_time": norm_ts(el.get("endDate")),
            })
        else:  # Workout
            yield ("workout", {
                "activity_type": el.get("workoutActivityType"),
                "duration_sec": _minutes_to_seconds(el.get("duration"), el.get("durationUnit")),
                "energy_kcal": to_float(el.get("totalEnergyBurned")),
                "distance": to_float(el.get("totalDistance")),
                "unit": el.get("totalDistanceUnit"),
                "start_time": norm_ts(el.get("startDate")),
                "end_time": norm_ts(el.get("endDate")),
            })
        # free memory: clear element and its preceding siblings
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
```

> Note the test's `bad` row: `norm_ts("bad-date")` returns `"bad-date"` (first 19 chars). That's acceptable — malformed timestamps are preserved verbatim and simply won't match a real day bucket during aggregation.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/parser.py backend/tests/test_parser.py backend/tests/fixtures/sample_export.xml
git commit -m "Add streaming Apple Health XML parser with zip support"
```

---

### Task 6: Daily-summary aggregation

**Files:**
- Create: `backend/app/aggregation.py`
- Test: `backend/tests/test_aggregation.py`

**Interfaces:**
- Consumes: `HealthRecord` rows already inserted for an `import_id`.
- Produces:
  - `aggregation.METRIC_MAP: dict[str, dict]` (per the Global Constraints table).
  - `aggregation.compute_daily_summaries(db: Session, user_id: int, import_id: int) -> int` — deletes this user's existing `DailySummary` rows, computes new ones from `health_records` for `import_id`, inserts them, returns the count inserted.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_aggregation.py`

```python
from app.models import HealthRecord, DailySummary
from app.aggregation import compute_daily_summaries

def _add(db, **kw):
    db.add(HealthRecord(user_id=1, import_id=1, source_name="w", **kw))

def test_compute_summaries(db_session):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aggregation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.aggregation'`.

- [ ] **Step 3: Write `backend/app/aggregation.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aggregation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/aggregation.py backend/tests/test_aggregation.py
git commit -m "Add SQL-based daily summary aggregation"
```

---

### Task 7: Import worker

**Files:**
- Create: `backend/app/worker.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `parser.open_export`/`iter_elements`, `aggregation.compute_daily_summaries`, models.
- Produces: `worker.run_import(import_id: int, file_path: str) -> None` — opens its own DB session; sets status `processing`; streams and bulk-inserts records/workouts (batch size 5000) tagged with `import_id`; computes summaries; **in one transaction** deletes the user's rows from prior imports (`health_records`/`workouts`/`daily_summaries` where `import_id != this`); sets `record_count`, `export_date`, `status="complete"`, `completed_at`. On any exception: rolls back this import's partial rows and sets `status="failed"` with `error_message`. Deletes `file_path` at the end.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_worker.py`

```python
import os
from app.models import User, Import, HealthRecord, Workout, DailySummary
from app.worker import run_import

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")

def _new_import(db, user_id):
    imp = Import(user_id=user_id, filename="export.xml", status="pending")
    db.add(imp); db.commit(); db.refresh(imp)
    return imp.id

def test_run_import_success(temp_db):
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
        assert db.query(Workout).count() == 1
        steps = db.query(DailySummary).filter_by(metric_key="steps", day="2026-06-01").one()
        assert steps.value == 1200
    assert not os.path.exists(tmp)  # temp file cleaned up

def test_reimport_replaces_previous(temp_db):
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

def test_failed_import_marks_failed(temp_db):
    with temp_db.SessionLocal() as db:
        db.add(User(id=1, username="jo", password_hash="x")); db.commit()
        iid = _new_import(db, 1)
    run_import(iid, "/does/not/exist.xml")
    with temp_db.SessionLocal() as db:
        assert db.get(Import, iid).status == "failed"
        assert db.get(Import, iid).error_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`.

- [ ] **Step 3: Write `backend/app/worker.py`**

```python
import os
from datetime import datetime, timezone
from app.db import SessionLocal
from app.models import Import, HealthRecord, Workout, DailySummary
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
        db.commit()

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker.py backend/tests/test_worker.py
git commit -m "Add import worker with transactional snapshot replace"
```

---

### Task 8: Import API

**Files:**
- Create: `backend/app/routers/imports.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_imports.py`

**Interfaces:**
- Consumes: `get_current_user`, `worker.run_import`, `get_settings().max_upload_mb`.
- Produces: `POST /api/imports` (multipart `file`) → saves upload to a temp path, creates `Import` row, schedules `run_import` via `BackgroundTasks`, returns `{import_id, status}`; `GET /api/imports` → this user's imports (newest first); `GET /api/imports/{id}` → one import (404 if not owned).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_imports.py`

```python
import io, os

def _login(client):
    client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    client.post("/api/auth/login", json={"username": "jo", "password": "pw12345"})

def test_upload_processes_synchronously_in_tests(client):
    _login(client)
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")
    data = open(fix, "rb").read()
    r = client.post("/api/imports", files={"file": ("export.xml", io.BytesIO(data), "text/xml")})
    assert r.status_code == 201
    iid = r.json()["import_id"]
    # TestClient runs BackgroundTasks synchronously after the response
    status = client.get(f"/api/imports/{iid}").json()
    assert status["status"] == "complete"
    assert status["record_count"] == 7

def test_cannot_read_others_import(client):
    _login(client)
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")
    iid = client.post("/api/imports",
        files={"file": ("export.xml", io.BytesIO(open(fix, "rb").read()), "text/xml")}).json()["import_id"]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "sis", "password": "pw12345"})
    client.post("/api/auth/login", json={"username": "sis", "password": "pw12345"})
    assert client.get(f"/api/imports/{iid}").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_imports.py -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Write `backend/app/routers/imports.py`**

```python
import os, tempfile
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Import, User
from app.security import get_current_user
from app.config import get_settings
from app.worker import run_import

router = APIRouter(prefix="/api/imports", tags=["imports"])

def _serialize(imp: Import) -> dict:
    return {
        "id": imp.id, "filename": imp.filename, "status": imp.status,
        "error_message": imp.error_message, "record_count": imp.record_count,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "completed_at": imp.completed_at.isoformat() if imp.completed_at else None,
    }

@router.post("", status_code=201)
async def create_import(bg: BackgroundTasks, file: UploadFile = File(...),
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = (file.filename or "").lower()
    if not (name.endswith(".xml") or name.endswith(".zip")):
        raise HTTPException(status_code=400, detail="Upload an export.xml or export.zip")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    suffix = ".zip" if name.endswith(".zip") else ".xml"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    size = 0
    with os.fdopen(fd, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close(); os.remove(tmp_path)
                raise HTTPException(status_code=413, detail="File too large")
            out.write(chunk)
    imp = Import(user_id=user.id, filename=file.filename or "export", status="pending")
    db.add(imp); db.commit(); db.refresh(imp)
    bg.add_task(run_import, imp.id, tmp_path)
    return {"import_id": imp.id, "status": imp.status}

@router.get("")
def list_imports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Import).filter(Import.user_id == user.id).order_by(Import.id.desc()).all()
    return [_serialize(i) for i in rows]

@router.get("/{import_id}")
def get_import(import_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    imp = db.get(Import, import_id)
    if not imp or imp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(imp)
```

- [ ] **Step 4: Modify `backend/app/main.py`** — add `from app.routers import auth, imports` and `app.include_router(imports.router)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_imports.py -v`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/imports.py backend/app/main.py backend/tests/test_imports.py
git commit -m "Add import upload/status API with per-user isolation"
```

---

### Task 9: Dashboard API

**Files:**
- Create: `backend/app/routers/dashboard.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `get_current_user`, `DailySummary`, `Workout`, `aggregation.METRIC_MAP`.
- Produces:
  - `GET /api/dashboard/summary` → `{metrics: [{metric_key, latest_value, latest_day, prev_value, change_pct}]}` for each metric that has data.
  - `GET /api/dashboard/metrics/{metric_key}?range=30d|90d|1y|all` → `{metric_key, points: [{day, value}]}` (ascending). 400 if `metric_key` unknown.
  - `GET /api/dashboard/records` → `{highlights: [{label, value, day}]}` (e.g. max steps day, longest workout).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_dashboard.py`

```python
import io, os

def _login_and_import(client):
    client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    client.post("/api/auth/login", json={"username": "jo", "password": "pw12345"})
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")
    client.post("/api/imports",
        files={"file": ("export.xml", io.BytesIO(open(fix, "rb").read()), "text/xml")})

def test_summary_and_series_and_records(client):
    _login_and_import(client)
    s = client.get("/api/dashboard/summary").json()
    keys = {m["metric_key"] for m in s["metrics"]}
    assert {"steps", "resting_hr", "sleep_hours"} <= keys

    series = client.get("/api/dashboard/metrics/steps?range=all").json()
    assert series["metric_key"] == "steps"
    assert series["points"][0] == {"day": "2026-06-01", "value": 1200}

    assert client.get("/api/dashboard/metrics/bogus").status_code == 400

    rec = client.get("/api/dashboard/records").json()
    labels = {h["label"] for h in rec["highlights"]}
    assert "Most steps in a day" in labels

def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/summary").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — 404/401 (routes missing).

- [ ] **Step 3: Write `backend/app/routers/dashboard.py`**

```python
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
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
```

- [ ] **Step 4: Modify `backend/app/main.py`** — include `dashboard.router`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dashboard.py -v && pytest -v`
Expected: PASS (dashboard tests, and the whole suite green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/dashboard.py backend/app/main.py backend/tests/test_dashboard.py
git commit -m "Add dashboard API: summary, series, and records"
```

---

## Phase 4 — Frontend

### Task 10: Frontend scaffold

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/vitest.setup.ts`

**Interfaces:**
- Produces a running Vite app with React Router, a dev proxy to the backend, and Vitest configured. `App` renders routes for `/login`, `/register`, `/`, `/import`.

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "health-analytics-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.24.0",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.6",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.0",
    "typescript": "^5.5.3",
    "vite": "^5.3.3",
    "vitest": "^2.0.1"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom", globals: true, setupFiles: "./vitest.setup.ts" },
});
```

- [ ] **Step 3: Write `frontend/tsconfig.json`, `frontend/index.html`, `frontend/vitest.setup.ts`**

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020", "useDefineForClassFields": true, "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext", "skipLibCheck": true, "moduleResolution": "bundler",
    "jsx": "react-jsx", "strict": true, "noEmit": true, "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vitest.setup.ts"]
}
```

`index.html`:
```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>Health Analytics</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

`vitest.setup.ts`:
```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 4: Write `frontend/src/main.tsx` and `frontend/src/App.tsx`**

`main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>
);
```

`App.tsx` (placeholder routes; filled in by later tasks):
```tsx
import { Routes, Route } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<div>login</div>} />
      <Route path="/register" element={<div>register</div>} />
      <Route path="/" element={<div>dashboard</div>} />
      <Route path="/import" element={<div>import</div>} />
    </Routes>
  );
}
```

- [ ] **Step 5: Install and verify build**

Run: `cd frontend && npm install && npm run build`
Expected: build succeeds, `dist/` produced.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "Add Vite + React + TS frontend scaffold"
```

---

### Task 11: API client + auth context

**Files:**
- Create: `frontend/src/api/client.ts`, `frontend/src/auth/AuthContext.tsx`, `frontend/src/components/ProtectedRoute.tsx`
- Test: `frontend/src/test/client.test.ts`

**Interfaces:**
- Produces:
  - `api` object: `register(u,p)`, `login(u,p)`, `logout()`, `me()`, `uploadImport(file)`, `listImports()`, `getImport(id)`, `getSummary()`, `getSeries(key,range)`, `getRecords()`. All use `fetch` with `credentials: "include"` and throw `ApiError` on non-2xx.
  - `AuthProvider` + `useAuth()` → `{user, loading, login, register, logout}`.
  - `ProtectedRoute` redirects to `/login` when no user.

- [ ] **Step 1: Write the failing test** — `frontend/src/test/client.test.ts`

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError } from "../api/client";

beforeEach(() => { vi.restoreAllMocks(); });

it("login posts credentials and returns json", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", username: "jo" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const res = await api.login("jo", "pw12345");
  expect(res.username).toBe("jo");
  const [, opts] = fetchMock.mock.calls[0];
  expect(opts.credentials).toBe("include");
});

it("throws ApiError on non-2xx", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 })));
  await expect(api.login("jo", "bad")).rejects.toBeInstanceOf(ApiError);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- client`
Expected: FAIL — cannot resolve `../api/client`.

- [ ] **Step 3: Write `frontend/src/api/client.ts`**

```ts
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req(path: string, opts: RequestInit = {}) {
  const res = await fetch(path, { credentials: "include", ...opts });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : null;
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText);
  return body;
}

function jsonPost(path: string, data: unknown) {
  return req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

export const api = {
  register: (username: string, password: string) => jsonPost("/api/auth/register", { username, password }),
  login: (username: string, password: string) => jsonPost("/api/auth/login", { username, password }),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  me: () => req("/api/auth/me"),
  uploadImport: (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return req("/api/imports", { method: "POST", body: fd });
  },
  listImports: () => req("/api/imports"),
  getImport: (id: number) => req(`/api/imports/${id}`),
  getSummary: () => req("/api/dashboard/summary"),
  getSeries: (key: string, range = "90d") => req(`/api/dashboard/metrics/${key}?range=${range}`),
  getRecords: () => req("/api/dashboard/records"),
};
```

- [ ] **Step 4: Write `frontend/src/auth/AuthContext.tsx` and `frontend/src/components/ProtectedRoute.tsx`**

`AuthContext.tsx`:
```tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "../api/client";

type User = { id: number; username: string } | null;
type Ctx = {
  user: User; loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  register: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
};
const AuthCtx = createContext<Ctx>(null!);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);
  const login = async (u: string, p: string) => { await api.login(u, p); setUser(await api.me()); };
  const register = async (u: string, p: string) => { await api.register(u, p); await login(u, p); };
  const logout = async () => { await api.logout(); setUser(null); };
  return <AuthCtx.Provider value={{ user, loading, login, register, logout }}>{children}</AuthCtx.Provider>;
}
```

`ProtectedRoute.tsx`:
```tsx
import { Navigate } from "react-router-dom";
import { ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading…</div>;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- client`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/auth frontend/src/components/ProtectedRoute.tsx frontend/src/test/client.test.ts
git commit -m "Add typed API client, auth context, and protected route"
```

---

### Task 12: Login & Register pages

**Files:**
- Create: `frontend/src/pages/Login.tsx`, `frontend/src/pages/Register.tsx`
- Modify: `frontend/src/main.tsx` (wrap in `AuthProvider`), `frontend/src/App.tsx` (wire pages + protected routes)
- Test: `frontend/src/test/login.test.tsx`

**Interfaces:**
- Consumes: `useAuth()`. Produces `Login` and `Register` page components. On success, navigate to `/`.

- [ ] **Step 1: Write the failing test** — `frontend/src/test/login.test.tsx`

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Login from "../pages/Login";

const loginFn = vi.fn().mockResolvedValue(undefined);
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ login: loginFn }) }));

it("submits username and password", async () => {
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/username/i), { target: { value: "jo" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "pw12345" } });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
  await waitFor(() => expect(loginFn).toHaveBeenCalledWith("jo", "pw12345"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- login`
Expected: FAIL — cannot resolve `../pages/Login`.

- [ ] **Step 3: Write `frontend/src/pages/Login.tsx` and `Register.tsx`**

`Login.tsx`:
```tsx
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try { await login(u, p); nav("/"); } catch { setErr("Invalid credentials"); }
  };
  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: "4rem auto", display: "grid", gap: 12 }}>
      <h1>Log in</h1>
      <label>Username<input value={u} onChange={e => setU(e.target.value)} /></label>
      <label>Password<input type="password" value={p} onChange={e => setP(e.target.value)} /></label>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      <button type="submit">Log in</button>
      <p>No account? <Link to="/register">Register</Link></p>
    </form>
  );
}
```

`Register.tsx` (same shape, calls `register`, button "Create account", links to `/login`):
```tsx
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try { await register(u, p); nav("/"); } catch { setErr("Could not register (username may be taken)"); }
  };
  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: "4rem auto", display: "grid", gap: 12 }}>
      <h1>Register</h1>
      <label>Username<input value={u} onChange={e => setU(e.target.value)} /></label>
      <label>Password<input type="password" value={p} onChange={e => setP(e.target.value)} /></label>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      <button type="submit">Create account</button>
      <p>Have an account? <Link to="/login">Log in</Link></p>
    </form>
  );
}
```

- [ ] **Step 4: Wire `main.tsx` and `App.tsx`**

`main.tsx` — wrap: `<BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter>` (import `AuthProvider`).

`App.tsx`:
```tsx
import { Routes, Route } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Import from "./pages/Import";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/import" element={<ProtectedRoute><Import /></ProtectedRoute>} />
    </Routes>
  );
}
```
> `Dashboard` and `Import` are created in Tasks 13–14. If building strictly in order, temporarily stub them as `export default () => null` and remove the stub when you reach those tasks.

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- login`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Login.tsx frontend/src/pages/Register.tsx frontend/src/main.tsx frontend/src/App.tsx frontend/src/test/login.test.tsx
git commit -m "Add login and register pages"
```

---

### Task 13: Import page

**Files:**
- Create: `frontend/src/pages/Import.tsx`
- Test: `frontend/src/test/import.test.tsx`

**Interfaces:**
- Consumes: `api.uploadImport`, `api.listImports`, `api.getImport`. Produces the `Import` page: file input + upload button; after upload, polls `getImport(id)` every 2s until `complete`/`failed`; shows import history from `listImports`.

- [ ] **Step 1: Write the failing test** — `frontend/src/test/import.test.tsx`

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Import from "../pages/Import";

vi.mock("../api/client", () => ({
  api: {
    listImports: vi.fn().mockResolvedValue([]),
    uploadImport: vi.fn().mockResolvedValue({ import_id: 1, status: "pending" }),
    getImport: vi.fn().mockResolvedValue({ id: 1, status: "complete", record_count: 7, filename: "export.xml" }),
  },
}));

it("uploads a file and shows completion", async () => {
  render(<MemoryRouter><Import /></MemoryRouter>);
  const file = new File(["<HealthData/>"], "export.xml", { type: "text/xml" });
  fireEvent.change(screen.getByLabelText(/export file/i), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: /upload/i }));
  await waitFor(() => expect(screen.getByText(/complete/i)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- import`
Expected: FAIL — cannot resolve `../pages/Import`.

- [ ] **Step 3: Write `frontend/src/pages/Import.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

type Imp = { id: number; status: string; record_count: number; filename: string; error_message?: string | null };

export default function Import() {
  const [file, setFile] = useState<File | null>(null);
  const [current, setCurrent] = useState<Imp | null>(null);
  const [history, setHistory] = useState<Imp[]>([]);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number>();

  const refresh = () => api.listImports().then(setHistory);
  useEffect(() => { refresh(); return () => clearInterval(timer.current); }, []);

  const poll = (id: number) => {
    timer.current = window.setInterval(async () => {
      const imp = await api.getImport(id);
      setCurrent(imp);
      if (imp.status === "complete" || imp.status === "failed") {
        clearInterval(timer.current); setBusy(false); refresh();
      }
    }, 2000);
  };

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    const { import_id } = await api.uploadImport(file);
    const imp = await api.getImport(import_id);
    setCurrent(imp);
    if (imp.status === "complete" || imp.status === "failed") { setBusy(false); refresh(); }
    else poll(import_id);
  };

  return (
    <div style={{ maxWidth: 640, margin: "2rem auto" }}>
      <h1>Import Apple Health data</h1>
      <p><Link to="/">← Dashboard</Link></p>
      <label>Export file (.xml or .zip)
        <input type="file" accept=".xml,.zip" onChange={e => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <button onClick={upload} disabled={!file || busy}>{busy ? "Processing…" : "Upload"}</button>
      {current && <p>Status: <strong>{current.status}</strong>
        {current.status === "complete" && ` — ${current.record_count} records`}
        {current.error_message && ` — ${current.error_message}`}</p>}
      <h2>History</h2>
      <ul>{history.map(h => <li key={h.id}>{h.filename} — {h.status} ({h.record_count})</li>)}</ul>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- import`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Import.tsx frontend/src/test/import.test.tsx
git commit -m "Add import page with upload and status polling"
```

---

### Task 14: Dashboard page + chart components

**Files:**
- Create: `frontend/src/components/StatTile.tsx`, `frontend/src/components/TrendCard.tsx`, `frontend/src/components/Highlights.tsx`, `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/test/dashboard.test.tsx`

**Interfaces:**
- Consumes: `api.getSummary`, `api.getSeries`, `api.getRecords`, `useAuth`. Produces the `Dashboard` page: a stat-tile row from `summary`, a `TrendCard` (Recharts line) per metric grouped by category, and a `Highlights` list. Empty state links to `/import`.

> Charting note: before styling the charts, read the `dataviz` skill for the palette and axis/legend/tooltip conventions. Use its light/dark-aware categorical colors rather than ad-hoc hex values.

- [ ] **Step 1: Write the failing test** — `frontend/src/test/dashboard.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Dashboard from "../pages/Dashboard";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, username: "jo" }, logout: vi.fn() }) }));
vi.mock("../api/client", () => ({
  api: {
    getSummary: vi.fn().mockResolvedValue({ metrics: [
      { metric_key: "steps", latest_value: 1200, latest_day: "2026-06-01", prev_value: 1000, change_pct: 20 }] }),
    getSeries: vi.fn().mockResolvedValue({ metric_key: "steps", points: [{ day: "2026-06-01", value: 1200 }] }),
    getRecords: vi.fn().mockResolvedValue({ highlights: [{ label: "Most steps in a day", value: 1200, day: "2026-06-01" }] }),
  },
}));

it("renders stat tiles and highlights", async () => {
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText(/steps/i)).toBeInTheDocument());
  expect(screen.getByText(/1200/)).toBeInTheDocument();
  expect(screen.getByText(/most steps in a day/i)).toBeInTheDocument();
});

it("shows empty state when no metrics", async () => {
  const { api } = await import("../api/client");
  (api.getSummary as any).mockResolvedValueOnce({ metrics: [] });
  (api.getRecords as any).mockResolvedValueOnce({ highlights: [] });
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText(/upload your apple health export/i)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- dashboard`
Expected: FAIL — cannot resolve `../pages/Dashboard`.

- [ ] **Step 3: Write the components**

`StatTile.tsx`:
```tsx
export default function StatTile({ label, value, change }: { label: string; value: number; change: number | null }) {
  const color = change == null ? "gray" : change >= 0 ? "green" : "crimson";
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, minWidth: 140 }}>
      <div style={{ fontSize: 12, textTransform: "uppercase", color: "#666" }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700 }}>{value.toLocaleString()}</div>
      {change != null && <div style={{ color }}>{change >= 0 ? "▲" : "▼"} {Math.abs(change)}%</div>}
    </div>
  );
}
```

`TrendCard.tsx`:
```tsx
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";

export default function TrendCard({ metricKey, title }: { metricKey: string; title: string }) {
  const [points, setPoints] = useState<{ day: string; value: number }[]>([]);
  useEffect(() => { api.getSeries(metricKey, "90d").then(r => setPoints(r.points)); }, [metricKey]);
  if (!points.length) return null;
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={points}>
          <XAxis dataKey="day" hide /><YAxis width={40} /><Tooltip />
          <Line type="monotone" dataKey="value" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

`Highlights.tsx`:
```tsx
export default function Highlights({ items }: { items: { label: string; value: number; day: string }[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h2>Highlights</h2>
      <ul>{items.map((h, i) => <li key={i}>{h.label}: <strong>{h.value.toLocaleString()}</strong> ({h.day})</li>)}</ul>
    </div>
  );
}
```

- [ ] **Step 4: Write `frontend/src/pages/Dashboard.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import StatTile from "../components/StatTile";
import TrendCard from "../components/TrendCard";
import Highlights from "../components/Highlights";

const LABELS: Record<string, string> = {
  steps: "Steps", distance: "Distance", active_energy: "Active energy",
  resting_hr: "Resting HR", heart_rate_avg: "Avg heart rate", sleep_hours: "Sleep (h)",
};

type Metric = { metric_key: string; latest_value: number; change_pct: number | null };

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [highlights, setHighlights] = useState<any[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([api.getSummary(), api.getRecords()]).then(([s, r]) => {
      setMetrics(s.metrics); setHighlights(r.highlights); setLoaded(true);
    });
  }, []);

  if (loaded && metrics.length === 0) {
    return (
      <div style={{ maxWidth: 640, margin: "4rem auto", textAlign: "center" }}>
        <h1>Welcome, {user?.username}</h1>
        <p>Upload your Apple Health export to get started.</p>
        <Link to="/import">Go to import →</Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 960, margin: "2rem auto" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Dashboard</h1>
        <div><Link to="/import">Import</Link> · <button onClick={logout}>Log out</button></div>
      </header>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "1rem 0" }}>
        {metrics.map(m => <StatTile key={m.metric_key} label={LABELS[m.metric_key] ?? m.metric_key}
          value={m.latest_value} change={m.change_pct} />)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
        {metrics.map(m => <TrendCard key={m.metric_key} metricKey={m.metric_key} title={LABELS[m.metric_key] ?? m.metric_key} />)}
      </div>
      <Highlights items={highlights} />
    </div>
  );
}
```

- [ ] **Step 5: Run tests + full frontend suite**

Run: `npm test`
Expected: PASS (all frontend tests). Then `npm run build` — succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components frontend/src/pages/Dashboard.tsx frontend/src/test/dashboard.test.tsx
git commit -m "Add dashboard page with stat tiles, trend charts, and highlights"
```

---

## Phase 5 — Deployment

### Task 15: Docker packaging

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`
- Modify: `backend/app/main.py` (serve built frontend static files)

**Interfaces:**
- Produces a single container that builds the frontend, copies it into the backend image, and serves it. `docker compose up` runs the app on `http://localhost:8000`.

- [ ] **Step 1: Modify `backend/app/main.py`** to serve the built SPA (add at the end, after routers)

```python
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_STATIC = os.environ.get("STATIC_DIR", "static")
if os.path.isdir(_STATIC):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index = os.path.join(_STATIC, "index.html")
        return FileResponse(index)
```

> This catch-all must be registered **after** all `/api/*` routers so API routes win.

- [ ] **Step 2: Write `Dockerfile`** (multi-stage)

```dockerfile
# --- frontend build ---
FROM node:20-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- backend runtime ---
FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .
COPY backend/ ./
COPY --from=fe /fe/dist ./static
ENV STATIC_DIR=/app/static
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:////data/health.db
      - SESSION_SECRET=${SESSION_SECRET}
      - COOKIE_SECURE=${COOKIE_SECURE:-false}
      - MAX_UPLOAD_MB=${MAX_UPLOAD_MB:-500}
    volumes:
      - ${DATA_DIR:-./data}:/data
    restart: unless-stopped
```

- [ ] **Step 4: Write `.env.example` and `.dockerignore`**

`.env.example`:
```
# Generate a strong secret: python -c "import secrets; print(secrets.token_hex(32))"
SESSION_SECRET=change-me
# Set true only when served over HTTPS (e.g. behind Cloudflare Tunnel)
COOKIE_SECURE=false
MAX_UPLOAD_MB=500
# Host folder for the SQLite file — point at an iCloud/Dropbox path for backups
DATA_DIR=./data
```

`.dockerignore`:
```
**/node_modules
**/.venv
**/__pycache__
**/dist
data
*.db
```

- [ ] **Step 5: Build and smoke-test**

Run:
```bash
cp .env.example .env   # then edit SESSION_SECRET
docker compose up --build -d
curl -s localhost:8000/api/health
```
Expected: `{"status":"ok"}`, and `http://localhost:8000` serves the login page.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example .dockerignore backend/app/main.py
git commit -m "Add Docker packaging serving API and built SPA"
```

---

### Task 16: README, .gitignore, and Cloudflare Tunnel docs

**Files:**
- Create: `.gitignore` (root)
- Modify: `README.md`

**Interfaces:** Documentation only — how to run, expose via Cloudflare Tunnel, and back up.

- [ ] **Step 1: Write root `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.pytest_cache/
node_modules/
frontend/dist/
backend/static/
data/
*.db
*.db-wal
*.db-shm
.env
.DS_Store
# never commit personal health data
*.xml
*.zip
!backend/tests/fixtures/*.xml
```

- [ ] **Step 2: Write `README.md`**

````markdown
# Health Analytics

Self-hosted Apple Health dashboard for a small set of private users. Each user uploads
their `export.xml` and views a personal summary dashboard. Runs free on your own machine.

## Run locally

```bash
cp .env.example .env
# set a strong SESSION_SECRET (python -c "import secrets; print(secrets.token_hex(32))")
docker compose up --build
```

Open http://localhost:8000 and register an account.

## Get your Apple Health export

On iPhone: Health app → your profile picture → **Export All Health Data** → share the
resulting `export.zip`. Upload that `.zip` (or the `export.xml` inside it) on the Import page.

## Share access with another person (Cloudflare Tunnel)

Install `cloudflared`, then run alongside the app:

```bash
cloudflared tunnel --url http://localhost:8000
```

It prints an HTTPS URL your other user can open and log in to. Set `COOKIE_SECURE=true`
in `.env` when serving over HTTPS. The app is reachable only while your machine is awake
and the tunnel is running.

## Backups

The database is a single SQLite file. Point `DATA_DIR` in `.env` at an iCloud/Dropbox
folder so the file is backed up automatically:

```
DATA_DIR=/Users/you/Library/Mobile Documents/com~apple~CloudDocs/health-analytics
```

## Development

- Backend: `cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload`
- Frontend: `cd frontend && npm install && npm run dev` (proxies `/api` to :8000)
- Tests: `cd backend && pytest` · `cd frontend && npm test`
````

- [ ] **Step 3: Verify the full test suites pass**

Run: `cd backend && pytest -v && cd ../frontend && npm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "Add gitignore and README with run, tunnel, and backup docs"
```

---

## Self-Review

**Spec coverage:**
- Manual `export.xml`/`.zip` upload → Tasks 5, 8. ✅
- Multi-user, username/password, sessions → Task 4. ✅
- Fully private per-user isolation → enforced in every router (Tasks 8, 9) + tested (`test_cannot_read_others_import`, `test_dashboard_requires_auth`). ✅
- Four metric categories + summary dashboard (tiles, trends, highlights) → Tasks 9, 14. ✅
- Streaming parse, constant memory → Task 5 (`iterparse` + clearing). ✅
- Full-snapshot replace on re-import → Task 7 + `test_reimport_replaces_previous`. ✅
- SQLite + WAL + Alembic → Tasks 2, 3. ✅
- Import job status + polling → Tasks 8, 13. ✅
- Error handling (failed import marked with message; generic auth errors) → Tasks 7, 4. ✅
- Self-hosted deploy, single container, Cloudflare Tunnel, SQLite backup → Tasks 15, 16. ✅
- Testing (parser fixtures, aggregation, transaction, per-user isolation, frontend) → Tasks 5–14. ✅

**Placeholder scan:** No TBD/TODO; every code step contains real code. The only forward reference (Dashboard/Import stubs in Task 12) is called out explicitly with the stub to use.

**Type consistency:** `run_import(import_id, file_path)` used identically in Tasks 7 and 8. `compute_daily_summaries(db, user_id, import_id)` consistent in Tasks 6 and 7. `metric_key` values match between `METRIC_MAP` (Task 6), dashboard `ALL_METRICS` (Task 9), and frontend `LABELS` (Task 14). API client method names (Task 11) match the routes in Tasks 4, 8, 9.

**Deviations from spec (intentional, noted):** Aggregation uses SQL `GROUP BY` rather than pandas — this better honors the spec's own "constant memory" constraint for GB-scale files. pandas remains a dependency for future ad-hoc analytics.
