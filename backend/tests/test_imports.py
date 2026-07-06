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
