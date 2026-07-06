import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'test.db'}")
    from app.config import get_settings
    get_settings.cache_clear()
    import importlib, app.db, app.models, app.worker
    importlib.reload(app.db)
    importlib.reload(app.models)
    # app.worker binds `SessionLocal` at import time (`from app.db import
    # SessionLocal`), so it must be reloaded after app.db to pick up the
    # fresh per-test engine/sessionmaker; otherwise background imports would
    # silently write to a stale (previous test's) database.
    importlib.reload(app.worker)
    app.db.init_db()
    return app.db


@pytest.fixture()
def db_session(temp_db):
    with temp_db.SessionLocal() as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    # app.security holds a module-global `_attempts` dict for per-IP login
    # rate limiting. conftest reloads app.db/models/worker/main per test but
    # NOT app.security (routers bind its functions by reference), so this
    # global otherwise accumulates login attempts across every test in the
    # session. Since all tests share the same TestClient IP and the suite runs
    # well within the 60s window, that leaks the limit and makes unrelated
    # tests fail with 429->401 once enough tests are added. Clear it per test.
    import app.security
    app.security._attempts.clear()
    yield
    app.security._attempts.clear()


@pytest.fixture()
def client(temp_db):
    import importlib, app.main
    importlib.reload(app.main)
    return TestClient(app.main.app)
