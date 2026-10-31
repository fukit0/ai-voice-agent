"""Profil karar kaydı: gerekçesiz eleme olmaz, karar anındaki sayılar saklanır, rapor profil bazlıdır."""
import pytest
from fastapi.testclient import TestClient

from app import decisions
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))


def row(pid):
    return next(r for r in client.get("/api/matrix").json()["rows"] if r["profile"] == pid)


def test_default_is_candidate_for_every_profile():
    assert all(r["decision"]["status"] == "aday" for r in client.get("/api/matrix").json()["rows"])


def test_elimination_requires_a_reason():
    r = client.put("/api/matrix/decisions/L1", json={"status": "elendi", "reason": "kötü"})
    assert r.status_code == 422 and "gerekçe" in r.json()["detail"]["message"]
    assert row("L1")["decision"]["status"] == "aday"


def test_unknown_profile_and_status():
    assert client.put("/api/matrix/decisions/ZZ", json={"status": "elendi", "reason": "x" * 20}).status_code == 404
    assert client.put("/api/matrix/decisions/L1", json={"status": "belki", "reason": "x" * 20}).status_code == 422


def test_decision_is_saved_with_snapshot_and_survives_new_data():
    reason = "Ilk ses p50 hedefin cok ustunde ve dogruluk dusuk"
    r = client.put("/api/matrix/decisions/L1", json={"status": "elendi", "reason": reason})
    assert r.status_code == 200 and r.json()["status"] == "elendi" and r.json()["snapshot"]["coverage"] is not None
    d = row("L1")["decision"]
    assert d["reason"] == reason and d["decided_at"]
    assert row("L2")["decision"]["status"] == "aday"          # başka profil etkilenmez


def test_revert_to_candidate_removes_record():
    client.put("/api/matrix/decisions/L1", json={"status": "secildi", "reason": "Dengeli ve en hizli ilk ses"})
    client.put("/api/matrix/decisions/L1", json={"status": "aday"})
    assert row("L1")["decision"]["status"] == "aday" and decisions.load() == {}


def test_report_is_per_profile_and_shows_reason_and_missing_reason_honestly():
    client.put("/api/matrix/decisions/L4", json={"status": "elendi", "reason": "Uretim hizi yetersiz, JSON hatasi yuksek"})
    md = client.get("/api/matrix/decisions/report").text
    lines = {ln.split("|")[1].strip().split(" ·")[0]: ln for ln in md.splitlines() if ln.startswith("| ") and "---" not in ln}
    assert "Elendi" in lines["L4"] and "JSON hatasi yuksek" in lines["L4"]
    assert "Aday" in lines["L2"]
    assert set(lines) >= {"L1", "L2", "L2-EL", "L3", "L4", "L5", "A1", "A1S", "A2", "A3"}


def test_license_elimination_gets_automatic_reason_in_report():
    rows = client.get("/api/matrix").json()["rows"]
    out = [r["profile"] for r in rows if r["eliminated"]]
    md = client.get("/api/matrix/decisions/report").text
    for pid in out:
        ln = next(x for x in md.splitlines() if x.startswith(f"| {pid} "))
        assert "Elendi (lisans)" in ln
