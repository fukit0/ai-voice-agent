"""Anket senaryosu: veri modeli, doğrulama, yer tutucu doldurma ve deterministik akış (core-004'ün temeli).

Kaynak: config/scenarios/<anahtar>.json (demo firmasının örnek senaryosunun birebir kopyası).
İlke (plan): akışı flow motoru yönetir; LLM yalnızca düğüm içinde konuşur ve cevabı yapılandırır.
Metin düzenlemeleri data/scenario-overrides/<anahtar>.json içinde saklanır; akış (dallar) düzenlenemez.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = re.compile(r"\{([A-Z0-9_]+)\}")
NO_ANSWER = "Cevap vermedi"
# Her adımdan tetiklenebilen çıkışlar (dal tablosunda görünmez): ret, "beni aramayın" talebi, sessiz hat.
# eval-llm niyetleriyle eşleşir: refuse -> kapanis_ret; dnc/silence ses hattı olaylarıdır.
GLOBAL_EXITS = {"refuse": "kapanis_ret", "dnc": "kapanis_dnc", "silence": "kapanis_sessiz"}

# Örnek değerler: önizleme ve playground için (okunuşlar Türkçe yazıyla).
SAMPLE_VALUES = {
    "ASISTAN": "Elif", "MUSTERI_ADI": "Ahmet Yılmaz", "HITAP": "Ahmet Bey", "MT_HITAP": "Mehmet Bey",
    "GORUSME_TARIHI": "yirmi iki Eylül", "GORUSME_SAATI": "on dört otuzda", "Q2": "sekiz",
    "CAGRI_MERKEZI": "sıfır dört yüz dört, yüz on iki, yirmi dokuz, altmış yedi",
    "RANDEVU": "yarın saat on beşte", "ILAN_ADEDI": "yüz", "ODEME_GUNU": "onunda",
    "AYLIK_UCRET": "dokuz bin beş yüz lira", "ASIM_UCRETI": "yüz elli lira",
    "TAAHHUT_BITIS": "yirmi beş Eylül iki bin yirmi yedi",
    "IKI_FA_ADIMLARI": "Hesabım, Güvenlik, İki adımlı doğrulama yolunu izleyerek açabilirsiniz",
}


def config_dir() -> Path:
    return Path(os.environ.get("SVA_SCENARIOS", ROOT / "config" / "scenarios"))


def overrides_dir() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "scenario-overrides"


class ScenarioError(ValueError):
    pass


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(config_dir().glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        sc = doc["scenario"]
        sc["_placeholders"] = doc.get("placeholders", {})
        sc["_sample_profile"] = doc.get("sample_profile", {})
        out[sc["key"]] = sc
    return out


def get(key: str) -> dict:
    sc = load_all().get(key)
    if sc is None:
        raise KeyError(key)
    return sc


def step_map(sc: dict) -> dict[str, dict]:
    return {s["key"]: s for s in sc["steps"]}


def validate(sc: dict) -> list[str]:
    """Bozuk akışı yakalar: olmayan hedef, çıkışsız adım, sonuçsuz terminal, ulaşılamayan adım."""
    errs: list[str] = []
    steps = step_map(sc)
    outcomes = {o["key"] for o in sc["outcomes"]}
    for intent, target in GLOBAL_EXITS.items():
        if target not in steps:
            errs.append(f"genel çıkış '{intent}' hedefi yok -> {target}")
    for s in sc["steps"]:
        for b in s["branches"]:
            if b["to"] not in steps:
                errs.append(f"{s['key']}: dal hedefi yok -> {b['to']}")
        if s["kind"] == "Terminal":
            if s["outcome"] not in outcomes:
                errs.append(f"{s['key']}: terminal sonucu tanımsız -> {s['outcome']}")
            if s["branches"]:
                errs.append(f"{s['key']}: terminal adımın dalı olmamalı")
        elif not s["branches"]:
            errs.append(f"{s['key']}: çıkışı olmayan adım")
    seen: set[str] = set()
    todo = [sc["steps"][0]["key"], *GLOBAL_EXITS.values()]
    while todo:
        k = todo.pop()
        if k in seen or k not in steps:
            continue
        seen.add(k)
        todo += [b["to"] for b in steps[k]["branches"]]
    for s in sc["steps"]:
        if s["key"] not in seen and s["applicable"]:
            errs.append(f"{s['key']}: başlangıçtan ulaşılamıyor")
    return errs


def load_overrides(key: str) -> dict[str, str]:
    f = overrides_dir() / f"{key}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_override(key: str, step: str, text: str | None) -> None:
    ov = load_overrides(key)
    if text is None:
        ov.pop(step, None)
    else:
        ov[step] = text
    overrides_dir().mkdir(parents=True, exist_ok=True)
    (overrides_dir() / f"{key}.json").write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf-8")


def effective_text(sc: dict, step: dict) -> str:
    return load_overrides(sc["key"]).get(step["key"], step["defaultText"])


def placeholders_in(text: str) -> list[str]:
    return list(dict.fromkeys(PLACEHOLDER.findall(text)))


def unknown_placeholders(sc: dict, text: str) -> list[str]:
    return [p for p in placeholders_in(text) if p not in sc["_placeholders"]]


def fill(text: str, values: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def sample_values(sc: dict) -> dict[str, str]:
    vals = dict(SAMPLE_VALUES)
    vals["KVKK_METNI"] = next((s["preview"] for s in sc["steps"] if s["key"] == "kvkk_metni"), "")
    return vals


def next_step(step: dict, answer) -> str | None:
    """Cevaba göre sonraki adım. answer: Choice -> seçenek value'su, YesNo -> bool, CallbackTime -> bool (zaman verdi mi),
    Score/Duration/OpenText -> değer ya da None (cevap yok), Statement -> yok sayılır. Terminal -> None."""
    br = step["branches"]
    if not br:
        return None
    kind = step["kind"]
    if kind == "Choice":
        label = next((c["label"] for c in step["choices"] if c["value"] == answer), None)
        hit = next((b for b in br if b["on"] == label), None)
    elif kind == "YesNo":
        hit = next((b for b in br if b["on"] == ("Evet" if answer else "Hayır")), None)
    elif kind == "CallbackTime":
        hit = next((b for b in br if b["on"] == ("Zaman verdi" if answer else "Zaman vermedi")), None)
    elif kind in ("Score", "Duration", "OpenText") and answer is None:
        hit = next((b for b in br if b["on"] == NO_ANSWER), None) or next((b for b in br if b["on"] == ""), None)
    else:
        hit = next((b for b in br if b["on"] == ""), None)
    if hit is None:
        raise ScenarioError(f"{step['key']}: '{answer}' cevabı için dal yok")
    return hit["to"]
