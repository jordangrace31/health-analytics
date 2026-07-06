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
