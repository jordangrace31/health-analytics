# Apple Health Analytics — Design Spec

**Date:** 2026-07-06
**Status:** Approved (brainstorming complete)

## Summary

A self-hosted web application where a small, fixed set of private users (initially
2 — the owner and his sister) each upload their Apple Health `export.xml` and view a
personal summary dashboard. A streaming parser turns the large export into pre-aggregated
daily summaries so dashboards load fast. The app runs for free on the owner's laptop and is
reachable remotely via Cloudflare Tunnel.

## Goals

- Import Apple Health data from the built-in **"Export All Health Data"** archive (`export.zip` / `export.xml`).
- Support **multiple users** (2 to start), each with **fully private** data — no sharing, no cross-user comparison.
- Present a **summary dashboard**: at-a-glance stat tiles, per-metric trend charts, and personal-record highlights.
- Cover four metric categories: **Activity**, **Heart**, **Sleep**, **Workouts & body**.
- Run at **$0 cost**, self-hosted on the owner's laptop.

## Non-Goals (YAGNI)

- Correlation analysis, goals/streaks tracking (may come later; not in this build).
- Cross-user comparison, leaderboards, or any data sharing.
- Automated/real-time sync from the phone (manual export upload only).
- A companion iOS/HealthKit app.
- Horizontal scale, multi-tenant SaaS concerns, or a managed cloud database.

## Users & Access

- **2 users**, each with an account (username + password). Extensible to a few more, but not designed for public signup at scale.
- Data is strictly scoped by `user_id` on every table and every query. A user can never read another user's data.

## Architecture

```
┌─────────────┐   upload export.zip   ┌──────────────────────────┐
│  React SPA  │ ────────────────────▶ │  FastAPI backend         │
│ (dashboard) │ ◀──── JSON / status ─ │  ├─ auth (sessions)      │
└─────────────┘                       │  ├─ import API           │
     served as static by backend      │  ├─ dashboard API        │
                                      │  └─ import worker ───────┼──┐
                                      └────────────┬─────────────┘  │
                                                   │                │ pandas
                                            ┌──────▼──────┐  parse+aggregate
                                            │   SQLite    │◀─────────┘
                                            │  (1 file)   │
                                            └─────────────┘
```

Four focused backend concerns, each its own module with a clear responsibility:

- **auth** — register, login, logout, current-user; session cookies.
- **imports** — accept uploads, track import jobs, expose status.
- **dashboard** — read-only aggregated data for the logged-in user.
- **import worker** — stream-parse the export and compute aggregates.

The FastAPI backend also serves the built static React frontend, so the whole app is a
single deployable unit.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, pandas (parsing/aggregation), lxml (`iterparse`), SQLAlchemy (DB-agnostic ORM/core), Alembic (migrations), passlib[argon2] (password hashing), uvicorn (server).
- **Database:** SQLite (single file), WAL mode enabled for read/write concurrency at 2-user scale.
- **Frontend:** React + TypeScript, Vite (build/dev), React Router, Recharts (charts). Charts follow the `dataviz` skill's palette/accessibility guidance (light/dark aware).
- **Packaging:** Docker Compose (single container: API + static frontend + SQLite volume).
- **Remote access:** Cloudflare Tunnel (`cloudflared`).

## Data Model (SQLite via SQLAlchemy)

- **`users`** — `id, username (unique), password_hash, created_at`
- **`imports`** — one row per uploaded file:
  `id, user_id, filename, status (pending|processing|complete|failed), error_message, record_count, export_date, created_at, completed_at`
- **`health_records`** — the raw firehose (millions of rows/user):
  `id, user_id, import_id, type, source_name, unit, value_num (nullable), value_text (nullable), start_time, end_time`
  Index on `(user_id, type, start_time)`.
- **`workouts`** —
  `id, user_id, import_id, activity_type, duration_sec, energy_kcal, distance, unit, start_time, end_time`
- **`daily_summaries`** — pre-aggregated rollups that power the dashboard:
  `user_id, metric_key, day, value` with a unique constraint on `(user_id, metric_key, day)`.
  `metric_key` examples: `steps`, `distance`, `active_energy`, `resting_hr`, `heart_rate_avg`, `sleep_hours`.

### Re-import strategy

Apple's export is a **full snapshot** every time. Rather than deduplicate, **each successful
import atomically replaces that user's previous data** within a single transaction: parse into
the new dataset, then in one transaction delete the user's prior `health_records` / `workouts`
/ `daily_summaries` and insert the new ones, and mark the import `complete`. On failure, the
transaction rolls back and the import is marked `failed` with an error message; existing data
is untouched.

## Import Pipeline (data flow)

1. **Upload** — user submits `export.zip`/`export.xml` to `POST /api/imports` (multipart). The
   backend validates size and that it looks like Apple Health XML, saves it to a temp path, creates
   an `imports` row (`status=pending`), and starts the worker.
2. **Parse & aggregate (worker)** — streams the XML with `lxml.iterparse` (constant memory even
   for GB-scale files), clearing elements as it goes. Records are batched into pandas frames;
   `Record` elements populate `health_records`, `Workout` elements populate `workouts`. Daily
   summaries are computed per metric with the appropriate aggregation (e.g. steps summed per day,
   resting HR averaged per day). The transactional swap (see above) commits the new dataset and
   sets `status=complete` (or `failed`).
3. **Poll** — the frontend polls `GET /api/imports/{id}` until `complete`, then loads the dashboard.
   The temp upload file is deleted after processing.

**Worker execution:** runs as an in-process background task (in a thread/process pool so it does
not block the API event loop). This is sufficient for 2 users with occasional imports. If
concurrency ever grows, the upgrade path is a Redis + RQ job queue — explicitly out of scope now.

### Metric aggregation map (initial)

| metric_key       | source record type(s)                       | daily aggregation |
|------------------|---------------------------------------------|-------------------|
| `steps`          | `HKQuantityTypeIdentifierStepCount`         | sum               |
| `distance`       | `HKQuantityTypeIdentifierDistanceWalkingRunning` | sum          |
| `active_energy`  | `HKQuantityTypeIdentifierActiveEnergyBurned`| sum               |
| `resting_hr`     | `HKQuantityTypeIdentifierRestingHeartRate`  | avg               |
| `heart_rate_avg` | `HKQuantityTypeIdentifierHeartRate`         | avg               |
| `sleep_hours`    | `HKCategoryTypeIdentifierSleepAnalysis`     | sum of asleep intervals |

This map is data-driven and extensible; unknown record types are still stored raw in
`health_records` so nothing is lost and new metrics can be added later without re-importing.

## API Surface

All endpoints except register/login require a valid session and filter by `user_id` server-side.

**Auth**
- `POST /api/auth/register` — `{username, password}` → creates user
- `POST /api/auth/login` — sets a secure, httpOnly session cookie
- `POST /api/auth/logout`
- `GET /api/auth/me` — current user (nil if not logged in)

**Imports**
- `POST /api/imports` — multipart upload → `{import_id, status}`
- `GET /api/imports` — this user's import history
- `GET /api/imports/{id}` — status polling

**Dashboard** (scoped to logged-in user)
- `GET /api/dashboard/summary` — stat tiles: latest value + period-over-period change for key metrics
- `GET /api/dashboard/metrics/{metric_key}?range=30d|90d|1y|all` — daily series for a chart
- `GET /api/dashboard/records` — recent personal-record highlights (e.g. most steps in a day, longest workout)

## Frontend

- **Vite** app; **React Router** for pages; a typed `fetch` API client that sends the session cookie automatically.
- **Charts:** Recharts (line/bar/sparkline mix), styled per the `dataviz` skill (coherent, accessible, light/dark aware).
- **Pages:**
  - **Login / Register**
  - **Dashboard** — stat-tile row; per-metric trend cards grouped by category (Activity / Heart / Sleep / Workouts & body); highlights section.
  - **Import** — upload control, live progress (polling), and import history.
- **Empty state** — a new user with no import sees a "Upload your Apple Health export to get started" guide.

## Auth & Security

- Passwords hashed with **argon2** (`passlib`). Sessions as **signed, httpOnly, SameSite cookies**.
- **`Secure` cookie flag** in production (served over HTTPS via Cloudflare Tunnel).
- Basic **rate limiting** on login attempts.
- **Upload validation:** size cap and a check that the file is genuine Apple Health XML before parsing; temp files deleted after processing.
- **Secrets** (session signing key, etc.) via environment variables — never committed. `.env.example` documents required config.
- CORS: since the frontend is served same-origin by the backend, CORS is closed by default (no cross-origin API access needed).

## Error Handling

- **Import failures** (malformed XML, unexpected schema, disk/parse errors) → import marked `failed` with a human-readable `error_message`; the transactional design guarantees existing data is untouched. The frontend surfaces the message on the Import page.
- **API errors** → consistent JSON error shape with appropriate HTTP status codes; the frontend shows friendly messages and never exposes stack traces.
- **Auth errors** → generic "invalid credentials" (no user-enumeration leak); 401 on unauthenticated access to protected endpoints.

## Testing

- **Backend (pytest):**
  - Parser unit tests using small synthetic `export.xml` fixtures covering steps / heart rate / sleep / workouts and malformed rows.
  - Aggregation correctness (each `metric_key` computes the right daily value).
  - The import-replaces-data transaction (success commits new data; failure rolls back and preserves old data).
  - API tests against a temp SQLite DB, including **per-user isolation** (user A cannot read user B's data).
- **Frontend (Vitest + React Testing Library):** dashboard rendering and auth-flow component tests with the API client mocked.
- A small **sample export fixture** is committed so the full pipeline is testable end-to-end without real personal data.

## Deployment

- **Host:** the owner's laptop (macOS). **Total cost: $0.**
- **Database:** SQLite file, WAL mode. Stored in (or copied to) an iCloud/Dropbox folder so data survives laptop loss — documented as a one-line backup step.
- **Packaging:** `docker compose up` starts a single container serving the API + static frontend, with the SQLite file on a mounted volume.
- **Remote access:** `cloudflared` exposes an HTTPS URL the sister opens and logs into — nothing for her to install. Available whenever the laptop is awake and online (accepted limitation of laptop hosting).
- **Config:** `.env.example` documents all environment variables. Alembic migrations create/upgrade the schema on startup.

## Repository Layout

```
health-analytics/
├── backend/
│   ├── app/              # FastAPI app: auth, imports, dashboard, worker, models
│   ├── migrations/       # Alembic
│   ├── tests/
│   └── pyproject.toml
├── frontend/             # Vite + React + TS app
│   ├── src/
│   └── package.json
├── docs/superpowers/specs/
├── docker-compose.yml
├── .env.example
└── README.md
```

## Open Questions / Future Work

- Additional metrics beyond the initial aggregation map (VO2 max, HRV, blood oxygen, body measurements) — easy to add later since raw records are retained.
- Correlations and goals/streaks features (explicitly deferred).
- Move from in-process worker to a job queue only if import concurrency ever becomes a problem.
