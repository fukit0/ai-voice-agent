from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_returns_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "lab-backend"
    assert body["version"]


def test_unknown_api_path_returns_json_404():
    res = client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")
