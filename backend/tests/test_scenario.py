import pytest
from fastapi.testclient import TestClient

from backend.app import scenario as S
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    return tmp_path


def anket():
    return S.get("anket")


def test_scenario_is_a_faithful_copy_and_valid():
    sc = anket()
    assert len(sc["steps"]) == 33 and len(sc["outcomes"]) == 11
    assert S.validate(sc) == []
    assert sc["steps"][0]["key"] == "giris"
    assert {s["key"] for s in sc["steps"] if not s["applicable"]} == {"q100"}  # yalnızca kurumsal müşteriye


def run(answers, start="giris"):
    """answers: {adım: cevap}; verilmeyen Statement/Score vb. için varsayılan: Statement -> yok, Score -> 8."""
    sc, steps = anket(), S.step_map(anket())
    k, path = start, []
    while True:
        st = steps[k]
        path.append(k)
        if st["kind"] == "Terminal":
            return path, st["outcome"]
        ans = answers.get(k, 8 if st["kind"] == "Score" else "metin" if st["kind"] == "OpenText" else None)
        k = S.next_step(st, ans)


def test_complete_path_ends_with_tamamlandi():
    path, outcome = run({"giris": "devam", "musaitlik": True, "q3": False, "q3x": True, "geri_arama_istegi": True,
                         "onay": True})
    assert outcome == "tamamlandi"
    assert path[:6] == ["giris", "musaitlik", "q3", "q3x", "anketor_oku", "q2"]
    assert "q100" not in path and "kvkk_metni" not in path
    assert path[-3:] == ["geri_arama_istegi", "onay", "kapanis"]


def test_listening_to_kvkk_goes_through_kvkk_step():
    path, _ = run({"giris": "dinle", "musaitlik": False, "randevu": True})
    assert path == ["giris", "kvkk_metni", "musaitlik", "randevu", "kapanis_randevu"]


@pytest.mark.parametrize("answers,outcome", [
    ({"giris": "devam", "musaitlik": False, "randevu": False}, "musait_degil"),
    ({"giris": "devam", "musaitlik": True, "q3": True}, "son_3_ay_katilim"),
    ({"giris": "devam", "musaitlik": True, "q3": False, "q3x": False}, "gorusmeyi_hatirlamiyor"),
])
def test_early_exits(answers, outcome):
    assert run(answers)[1] == outcome


def test_q2_no_answer_skips_reason_question():
    sc = anket()
    steps = S.step_map(sc)
    assert S.next_step(steps["q2"], 8) == "q4"
    assert S.next_step(steps["q2"], None) == "q3_giris"


def test_double_consent_flow():
    steps = S.step_map(anket())
    assert S.next_step(steps["onay"], False) == "onay_tekrar"
    assert S.next_step(steps["onay_tekrar"], False) == "kapanis"


def test_invalid_answer_has_no_branch():
    with pytest.raises(S.ScenarioError):
        S.next_step(S.step_map(anket())["giris"], "belki")


def test_validate_catches_broken_flow():
    sc = anket()
    broken = {**sc, "steps": [dict(s) for s in sc["steps"]]}
    broken["steps"][2] = {**broken["steps"][2], "branches": [{"on": "Evet", "to": "yok_boyle_adim"}]}
    errs = S.validate(broken)
    assert any("dal hedefi yok" in e for e in errs) and any("ulaşılamıyor" in e for e in errs)


def test_api_list_and_detail(data):
    r = client.get("/api/scenarios").json()
    assert r[0]["key"] == "anket" and r[0]["steps"] == 33 and r[0]["problems"] == []
    d = client.get("/api/scenarios/anket").json()
    giris = d["steps"][0]
    assert giris["branches"][0] == {"on": "Evet, dinlemek istedi", "to": "kvkk_metni", "to_title": "KVKK aydınlatma metni (IVR)"}
    assert "Elif" in giris["spoken"] and "{" not in giris["spoken"]
    q3x = next(s for s in d["steps"] if s["key"] == "q3x")
    assert "yirmi iki Eylül tarihinde saat on dört otuzda" in q3x["spoken"]
    assert client.get("/api/scenarios/yok").status_code == 404


def test_edit_text_save_reset_and_validation(data):
    url = "/api/scenarios/anket/steps/musaitlik/text"
    r = client.put(url, json={"text": "Şimdi birkaç dakikanız var mı {HITAP}?"})
    assert r.status_code == 200 and r.json()["edited"] and "Ahmet Bey" in r.json()["spoken"]
    assert client.get("/api/scenarios/anket").json()["steps"][2]["text"].startswith("Şimdi birkaç")
    assert client.put(url, json={"text": "Merhaba {OLMAYAN}"}).status_code == 400
    assert client.put(url, json={"text": "  "}).status_code == 400
    r = client.delete(url).json()
    assert not r["edited"] and r["text"] == "Görüşme yapmak için müsait misiniz?"
    # varsayılan metne eşit kaydetmek düzenleme sayılmaz
    assert not client.put(url, json={"text": "Görüşme yapmak için müsait misiniz?"}).json()["edited"]


def test_preview_normalizes_numbers_and_reports_unknown_placeholders(data):
    r = client.post("/api/scenarios/anket/preview", json={"text": "{HITAP}, 1.250 TL {XYZ}"}).json()
    assert r["spoken"].startswith("Ahmet Bey, bin iki yüz elli lira") and r["unknown_placeholders"] == ["XYZ"]
