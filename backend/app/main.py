from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.db import init_db
from app.routers import auth, imports, dashboard

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
app.include_router(imports.router)
app.include_router(dashboard.router)
