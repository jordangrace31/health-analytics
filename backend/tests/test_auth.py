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

def test_duplicate_username_integrity_race_returns_409(client, monkeypatch):
    # First registration succeeds and is committed.
    assert client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"}).status_code == 201
    # Simulate a TOCTOU race: the fast-path SELECT check misses the existing row
    # (returns None), so the INSERT hits the DB unique constraint. This must be
    # caught and surface as 409, never a 500.
    from sqlalchemy.orm import Query
    monkeypatch.setattr(Query, "first", lambda self: None)
    r = client.post("/api/auth/register", json={"username": "jo", "password": "pw12345"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Username taken"
