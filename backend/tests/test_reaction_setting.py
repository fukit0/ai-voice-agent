"""hum-001 aç/kapa ayarı (docs/cevaba-bagli-tepki-ayari.md): kapalıyken cevaba bağlı tepki üretilmez, hum-001 öncesi sabit onay
(acknowledgements sırayla) söylenir; açıkken davranış değişmez. Kalıcılık (data/reactions.json), API GET/PUT, arama başı kopyası,
arama kaydı (config.reactions) ve tur kaydı (reaction kaynağı). Gerçek ses/telefon burada denenmez."""
import asyncio
import json
import random

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import persona as P
from backend.app import reaction_setting as R
from backend.app import scenario as S
from backend.app.main import app
from backend.app.voice.flow import FlowDriver
from backend.tests.test_flow import ScriptedLLM, ans

POOL = {"yes": ["Y1.", "Y2."], "no": ["N1.", "N2."], "other": ["O1.", "O2."]}


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    return tmp_path


def persona(**kw):
    return {**P.defaults(), "acknowledgements": ["A.", "B."], "reactions": POOL, "reaction_rate": 1.0, **kw}


def run(enabled: bool, p: dict, answers=(("devam", "devam"), (True, "evet"), (False, "hayır"))):
    fd = FlowDriver(S.get("anket"), None, persona=p, rng=random.Random(5))
    fd.reactions_enabled = enabled
    fd.start()
    said, events = [], []
    for v, u in answers:
        rep = fd.handle_structured({"intent": "answer", "value": v}, u)
        events += [e for e in rep.events if e["type"] in ("reaction", "reaction_skipped")]
        said.append(rep.utterances[0])
    return said, events


def test_off_speaks_old_fixed_acks_in_order_and_no_pool_reaction(data):
    p = persona()
    said, events = run(False, p)
    assert said == ["A.", "B.", "A."]                                       # hum-001 öncesi: sırayla onay
    assert not any(x in v for v in POOL.values() for x in said)              # havuzdan hiçbir tepki yok
    assert [e["source"] for e in events] == ["fixed_ack"] * 3 and all(e["bucket"] == "ack" for e in events)
    assert p["reactions"] == POOL and p["reaction_rate"] == 1.0              # havuz/oran dokunulmadan duruyor


def test_off_ignores_reaction_rate_like_old_behaviour(data):
    said, events = run(False, persona(reaction_rate=0.0))
    assert said == ["A.", "B.", "A."] and not any(e["type"] == "reaction_skipped" for e in events)


def test_on_is_unchanged_hum001_behaviour(data):
    said, events = run(True, persona())
    assert said[0] in POOL["other"] and said[1] in POOL["yes"] and said[2] in POOL["no"]
    assert [e["source"] for e in events] == ["pool"] * 3 and [e["bucket"] for e in events] == ["other", "yes", "no"]
    # oran 0 iken açıkta tepki atlanır ve kayda 'skipped' düşer
    _, ev0 = run(True, persona(reaction_rate=0.0))
    assert [e["type"] for e in ev0] == ["reaction_skipped"] * 3


def test_default_flow_keeps_reactions_enabled():
    assert FlowDriver(S.get("anket"), None, persona=persona()).reactions_enabled is True


def test_context_reaction_stays_when_off(data):
    """off-001 bağlam tepkisi (şikayete empati) bu ayardan bağımsız; yalnız hum-001 kova tepkisi kapanır."""
    _, events = run(False, persona(), answers=(("devam", "devam"), (True, "evet ama çok kötü bir deneyimdi")))
    assert events[1]["source"] == "context"


def test_persistence_default_toggle_reset_and_corrupt_file(data):
    assert R.enabled() is True and not R.path().exists()                    # varsayılan açık, dosya yok
    assert R.save(False) is False and R.enabled() is False
    assert json.loads(R.path().read_text(encoding="utf-8")) == {"enabled": False}
    assert R.save(True) is True and not R.path().exists()                   # varsayılana eşit: dosya yazılmaz
    R.save(False)
    assert R.save(None) is True and R.enabled() is True
    R.path().write_text("{bozuk", encoding="utf-8")
    assert R.enabled() is True                                              # bozuk dosya: varsayılan
    R.path().write_text('{"enabled": "hayir"}', encoding="utf-8")
    assert R.enabled() is True
    with pytest.raises(ValueError):
        R.save("kapali")


def test_persona_pools_survive_toggle(data):
    before = P.load()
    R.save(False)
    R.save(True)
    assert P.load() == before


def test_api_get_put(data):
    c = TestClient(app)
    g = c.get("/api/reactions").json()
    assert g["enabled"] is True and g["default"] is True and g["overridden"] is False
    assert g["reaction_rate"] == P.load()["reaction_rate"] and g["acknowledgements"] == P.load()["acknowledgements"]
    assert set(g["pool_sizes"]) == set(P.REACTION_BUCKETS)
    r = c.put("/api/reactions", json={"enabled": False}).json()
    assert r["enabled"] is False and r["overridden"] is True and c.get("/api/reactions").json()["enabled"] is False
    assert c.put("/api/reactions", json={}).json()["enabled"] is False                 # alan yoksa değişmez
    assert c.put("/api/reactions", json={"enabled": None}).json()["enabled"] is True   # null: varsayılan
    assert c.put("/api/reactions", json={"enabled": "abc"}).status_code == 422


def test_apply_to_copies_value_at_call_start(data):
    R.save(False)
    fd = FlowDriver(S.get("anket"), None, persona=persona())
    R.apply_to(fd)
    R.save(True)                                                            # arama sürerken ayar değişir
    assert fd.reactions_enabled is False                                    # açık arama eski ayarla sürer
    fd2 = FlowDriver(S.get("anket"), None, persona=persona())
    R.apply_to(fd2)
    assert fd2.reactions_enabled is True                                    # yeni arama yeni ayarla


@pytest.mark.parametrize("enabled", [True, False])
def test_call_record_has_setting_and_turn_reaction_source(tmp_path, monkeypatch, enabled):
    from backend.tests.test_turntaking import ScriptSTT
    from backend.tests.test_voice import make_session, settle, silence, speech

    async def go():
        turns = ["devam", "evet"]
        s, _, _ = make_session(tmp_path, monkeypatch, stt=ScriptSTT(turns))
        s.flow = FlowDriver(S.get("anket"), ScriptedLLM([ans("devam"), ans(True)]), persona=persona(), rng=random.Random(1))
        s.flow.reactions_enabled = enabled
        s.flow.start()
        s._apply_endpointing()
        for _ in turns:
            s.state = "listening"
            s._apply_endpointing()
            s.feed(np.concatenate([silence(0.3), speech(1.0), silence(1.5)]))
            await settle(s)
        path = await s.close()
        return json.loads(path.read_text(encoding="utf-8"))

    saved = asyncio.run(go())
    assert saved["config"]["reactions"] == {"enabled": enabled}
    rx = [t["reaction"] for t in saved["turns"] if "reaction" in t]
    assert len(rx) == 2
    assert [r["source"] for r in rx] == (["pool", "pool"] if enabled else ["fixed_ack", "fixed_ack"])


def test_call_record_reactions_none_without_persona(tmp_path, monkeypatch):
    from backend.tests.test_voice import make_session

    async def go():
        s, _, _ = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), None)                           # realtime gibi: persona yok -> tepki katmanı yok
        s.flow.start()
        path = await s.close()
        return json.loads(path.read_text(encoding="utf-8"))

    assert asyncio.run(go())["config"]["reactions"] is None
