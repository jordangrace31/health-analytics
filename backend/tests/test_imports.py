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
    assert status["export_date"] == "2026-07-01 09:00:00"

def test_cannot_read_others_import(client):
    _login(client)
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")
    iid = client.post("/api/imports",
        files={"file": ("export.xml", io.BytesIO(open(fix, "rb").read()), "text/xml")}).json()["import_id"]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "sis", "password": "pw12345"})
    client.post("/api/auth/login", json={"username": "sis", "password": "pw12345"})
    assert client.get(f"/api/imports/{iid}").status_code == 404


def test_wrong_extension_rejected(client):
    _login(client)
    r = client.post("/api/imports",
        files={"file": ("notes.txt", io.BytesIO(b"not an export"), "text/plain")})
    assert r.status_code == 400
    # No Import row should have been created for a rejected upload.
    assert client.get("/api/imports").json() == []


def test_oversized_upload_rejected_and_temp_cleaned(client, tmp_path, monkeypatch):
    _login(client)
    import tempfile, app.config

    # Route the router's mkstemp into a directory we control so we can assert
    # no partial temp file survives the rejected upload.
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    real_mkstemp = tempfile.mkstemp

    def controlled_mkstemp(*args, **kwargs):
        kwargs["dir"] = str(upload_dir)
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", controlled_mkstemp)

    # Force any non-empty upload over the size limit (0 MB => 0 bytes allowed),
    # matching how temp_db manipulates settings (env + cache_clear).
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")
    app.config.get_settings.cache_clear()

    fix = os.path.join(os.path.dirname(__file__), "fixtures", "sample_export.xml")
    data = open(fix, "rb").read()
    r = client.post("/api/imports", files={"file": ("export.xml", io.BytesIO(data), "text/xml")})
    assert r.status_code == 413
    # No Import row, and the partial temp file was cleaned up.
    assert client.get("/api/imports").json() == []
    assert os.listdir(upload_dir) == []
