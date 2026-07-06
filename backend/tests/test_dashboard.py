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
