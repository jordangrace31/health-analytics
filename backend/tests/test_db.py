import importlib

from sqlalchemy import text


def test_wal_mode_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    from app.config import get_settings
    get_settings.cache_clear()

    # app.db binds its module-level engine/SessionLocal from get_settings() at
    # import time. If app.db (or app.models, which app.db imports inside
    # init_db()) was already imported earlier in the test session, a plain
    # re-import would just return the cached module bound to the old
    # database_url. Reload both, after the env var + settings cache are
    # updated, so the engine created here is genuinely bound to tmp_path and
    # never touches the default ./data/health.db.
    import app.db
    import app.models
    importlib.reload(app.db)
    importlib.reload(app.models)

    app.db.init_db()
    with app.db.SessionLocal() as s:
        mode = s.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
