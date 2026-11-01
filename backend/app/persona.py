"""Persona (core-005, plan F1.5): ajanın adı, tonu, hitap tarzı, cümle uzunluğu sınırı ve doğal onay sözleri.

Tek kaynak: config/persona.json (varsayılan) + data/persona.json (ekrandan yapılan düzenleme). Persona üç yerde etkilidir:
1) serbest sohbet sistem istemi ve açılış cümlesi (`system_prompt`, `greeting`),
2) senaryo metinlerindeki {ASISTAN} değeri (`scenario_values`),
3) kademeli hatta cevaptan sonra söylenen doğal onay sözü (`ack`; realtime hatta uygulanmaz).
Rapor (`report`) kayıtlı oturumlardaki ajan cümlelerinin uzunluğunu ve yasak söz kullanımını ölçer; kural dışı kısmı gösterir.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TONES = {
    "samimi": "sıcak, samimi ama saygılı, doğal ve rahat konuşan",
    "resmi": "kibar, ölçülü ve resmî ama soğuk olmayan bir üslupla konuşan",
    "enerjik": "canlı, neşeli ve enerjik, heyecanını sesinden hissettiren ama abartmayan",
    "sakin": "yumuşak, sakin ve telaşsız, müşteriyi rahatlatan bir üslupla konuşan",
}
ADDRESS = {
    "bey_hanim": "Müşteriye 'Ahmet Bey' / 'Ayşe Hanım' gibi ad ve Bey/Hanım ile hitap et.",
    "ad": "Müşteriye yalnızca adıyla hitap et (soyadı kullanma).",
    "siz": "Müşteriye ad kullanmadan, yalnızca 'siz' diyerek hitap et.",
}
DEFAULT: dict = {
    "name": "Ayşe",
    "tone": "samimi",
    "address": "bey_hanim",
    "max_sentences": 2,
    "max_words_per_sentence": 14,
    "speed": 1.0,
    "acknowledgements": ["Anladım.", "Teşekkür ederim.", "Peki, tamamdır.", "Not aldım."],
    "avoid_phrases": ["Sayın müşterimiz", "bilgilerinize sunarız", "tarafımızdan"],
    "extra_rules": "",
    "reaction_rate": 1.0,    # cevaptan sonra tepki söyleme olasılığı (1.0 = her cevaptan sonra; insanlar her cevaba tepki vermez)
    "reactions": {},         # kova -> tepki cümleleri (boşsa yalnız acknowledgements sırayla döner)
}
REACTION_BUCKETS = {
    "score_low": "düşük puan (aralığın alt %40'ı)", "score_mid": "orta puan", "score_high": "yüksek puan (aralığın üst %25'i)",
    "yes": "evet cevabı", "no": "hayır cevabı", "other": "seçenek, süre, serbest metin",
}
_LIMITS = {"name": (1, 30), "max_sentences": (1, 5), "max_words_per_sentence": (5, 40)}
_SENT = re.compile(r"(?<=[.!?…])\s+")
_WORD = re.compile(r"[\wçğıöşüÇĞİÖŞÜ’'-]+")


def _default_path() -> Path:
    return Path(os.environ.get("SVA_PERSONA_DEFAULT", ROOT / "config" / "persona.json"))


def _override_path() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "persona.json"


def defaults() -> dict:
    p = _default_path()
    return {**DEFAULT, **(json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {})}


def validate(p: dict) -> list[str]:
    """Sorun listesi (boş = geçerli). Ekran bu iletileri doğrudan gösterir."""
    errs: list[str] = []
    name = str(p.get("name", "")).strip()
    if not _LIMITS["name"][0] <= len(name) <= _LIMITS["name"][1]:
        errs.append("Ad 1-30 karakter olmalı.")
    elif not re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü' -]+", name):
        errs.append("Ad yalnızca harf içerebilir (TTS'te okunuşu bozulmasın).")
    if p.get("tone") not in TONES:
        errs.append(f"Ton şunlardan biri olmalı: {', '.join(TONES)}.")
    if p.get("address") not in ADDRESS:
        errs.append(f"Hitap şunlardan biri olmalı: {', '.join(ADDRESS)}.")
    for k in ("max_sentences", "max_words_per_sentence"):
        lo, hi = _LIMITS[k]
        if not isinstance(p.get(k), int) or isinstance(p.get(k), bool) or not lo <= p[k] <= hi:
            errs.append(f"{k} {lo}-{hi} arasında tam sayı olmalı.")
    for k in ("acknowledgements", "avoid_phrases"):
        v = p.get(k)
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v) or len(v) > 12:
            errs.append(f"{k}: en çok 12 boş olmayan metin listesi olmalı.")
    rr = p.get("reaction_rate", 1.0)
    if isinstance(rr, bool) or not isinstance(rr, (int, float)) or not 0 <= rr <= 1:
        errs.append("Tepki oranı 0-1 arasında olmalı (1 = her cevaptan sonra).")
    rx = p.get("reactions", {})
    if not isinstance(rx, dict) or set(rx) - set(REACTION_BUCKETS):
        errs.append(f"reactions: kovalar şunlardan olmalı: {', '.join(REACTION_BUCKETS)}.")
    else:
        for b, items in rx.items():
            if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items) or len(items) > 12:
                errs.append(f"reactions.{b}: en çok 12 boş olmayan metin listesi olmalı.")
                continue
            for x in items:
                if "?" in x:
                    errs.append(f"Tepki soru içeremez (sıradaki soruyla karışır): '{x}'")
                if isinstance(p.get("max_words_per_sentence"), int) and len(_WORD.findall(x)) > p["max_words_per_sentence"]:
                    errs.append(f"Tepki cümle sınırını aşıyor: '{x}'")
                if any(a.casefold() in x.casefold() for a in (p.get("avoid_phrases") or []) if isinstance(a, str) and a.strip()):
                    errs.append(f"Tepki yasak kalıp içeriyor: '{x}'")
    sp = p.get("speed", 1.0)
    if isinstance(sp, bool) or not isinstance(sp, (int, float)) or not 0.7 <= sp <= 1.3:
        errs.append("Konuşma hızı 0,7-1,3 arasında olmalı (1,0 = normal).")
    if len(str(p.get("extra_rules", ""))) > 600:
        errs.append("Ek kurallar en çok 600 karakter olabilir.")
    limit = p.get("max_words_per_sentence")
    acks = p.get("acknowledgements")
    if isinstance(limit, int) and isinstance(acks, list):
        for a in acks:
            if isinstance(a, str) and len(_WORD.findall(a)) > limit:
                errs.append(f"Onay sözü cümle sınırını aşıyor: '{a}'")
    return errs


def load() -> dict:
    d = defaults()
    p = _override_path()
    if p.is_file():
        try:
            d.update(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass   # bozuk dosya: varsayılana düş, ekran Sıfırla ile temizler
    return d


def save(p: dict) -> dict:
    clean = {k: p[k] for k in DEFAULT if k in p}
    merged = {**load(), **clean}
    merged["name"] = str(merged["name"]).strip()
    merged["acknowledgements"] = [a.strip() for a in merged["acknowledgements"]]
    merged["avoid_phrases"] = [a.strip() for a in merged["avoid_phrases"]]
    merged["reactions"] = {b: [x.strip() for x in v] for b, v in (merged.get("reactions") or {}).items()}
    path = _override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def reset() -> dict:
    p = _override_path()
    if p.is_file():
        p.unlink()
    return load()


def system_prompt(p: dict | None = None) -> str:
    p = p or load()
    rules = [
        f"Sen sahibinden.com adına müşterilerle telefonda konuşan {p['name']} adlı, {TONES[p['tone']]} bir anket görevlisisin.",
        f"Türkçe konuş. En fazla {p['max_sentences']} kısa cümleyle yanıt ver; her cümle en çok {p['max_words_per_sentence']} kelime olsun.",
        "Liste, madde işareti ve emoji kullanma. Sayıları ve fiyatları rakamla yazabilirsin.",
        ADDRESS[p["address"]],
        "Müşteri bir şey sorarsa kısaca yanıtla, sonra nazikçe konuya dön.",
        "Yapay zeka olup olmadığın sorulursa dürüstçe sahibinden.com'un dijital asistanı olduğunu söyle.",
    ]
    if p["acknowledgements"]:
        rules.append("Cevabı aldığını doğal onaylarla belli et, örneğin: " + "; ".join(f"'{a}'" for a in p["acknowledgements"]) + ".")
    if p["avoid_phrases"]:
        rules.append("Şu kalıpları ASLA kullanma: " + "; ".join(f"'{a}'" for a in p["avoid_phrases"]) + ".")
    if p["extra_rules"].strip():
        rules.append(p["extra_rules"].strip())
    return " ".join(rules)


def greeting(p: dict | None = None) -> str:
    p = p or load()
    return f"Merhaba, ben {p['name']}. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?"


def scenario_values(p: dict | None = None) -> dict[str, str]:
    return {"ASISTAN": (p or load())["name"]}


def ack(p: dict | None, n: int) -> str | None:
    """n. cevaptan sonra söylenecek onay sözü (sırayla döner; liste boşsa None)."""
    acks = (p or load())["acknowledgements"]
    return acks[n % len(acks)] if acks else None


def bucket_of(step: dict, value) -> str:
    """Kabul edilen cevabın tepki kovası. Puan aralığa göre: alt %40 düşük, üst %25 yüksek, arası orta."""
    kind = step.get("kind")
    if kind == "YesNo":
        return "yes" if value is True else "no" if value is False else "other"
    if kind == "Score" and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo = 0 if step.get("code") == "Q12" else step.get("min", 1)
        hi = step.get("max", 10)
        frac = (value - lo) / (hi - lo) if hi > lo else 1.0
        return "score_low" if frac < 0.4 else "score_high" if frac >= 0.75 else "score_mid"
    return "other"


def reaction(p: dict | None, step: dict, value, used: list[str], rng, n: int = 0) -> tuple[str | None, str | None]:
    """Cevaptan sonra söylenecek kısa tepki: (metin, kova). Cevaba bağlı kovadan seçilir, aynı aramada tekrar etmez;
    reaction_rate'e göre bazen hiç söylenmez. Kova tanımsızsa eski davranış: acknowledgements sırayla döner."""
    p = p or load()
    rate = p.get("reaction_rate", 1.0)
    if rate < 1.0 and rng.random() >= rate:
        return None, None
    pools = p.get("reactions") or {}
    bucket = bucket_of(step, value)
    pool = pools.get(bucket) or []
    if not pool:
        text = ack(p, n)
        return (text, "ack") if text else (None, None)
    fresh = [x for x in pool if x not in used] or [x for x in pool if x != (used[-1] if used else None)] or pool
    text = rng.choice(fresh)
    used.append(text)
    return text, bucket


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


def sentence_stats(texts: list[str], p: dict | None = None) -> dict:
    """Ajan metinlerinden cümle sayısı, cümle başına ortalama kelime, sınırı aşan cümleler ve yasak söz kullanımı."""
    p = p or load()
    sents = [s for t in texts for s in split_sentences(t)]
    counts = [len(_WORD.findall(s)) for s in sents]
    low = " ".join(texts).casefold()
    return {
        "utterances": len(texts), "sentences": len(sents),
        "avg_words_per_sentence": round(sum(counts) / len(counts), 1) if counts else None,
        "max_words": max(counts) if counts else None,
        "over_limit": [{"text": s, "words": c} for s, c in zip(sents, counts) if c > p["max_words_per_sentence"]],
        "over_limit_rate": round(sum(c > p["max_words_per_sentence"] for c in counts) / len(counts), 3) if counts else None,
        "avoid_hits": sorted({a for a in p["avoid_phrases"] if a.casefold() in low}),
    }


def report(limit: int = 20, p: dict | None = None) -> dict:
    """Kayıtlı oturumlardaki (data/voice-sessions) ajan cümlelerini özetler. Ölçüm üretmez; gerçek aramalar gerekir."""
    p = p or load()
    folder = Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "voice-sessions"
    files = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit] if folder.is_dir() else []
    sessions, all_texts = [], []
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        texts = [t["text"] for t in doc.get("transcript", []) if t.get("role") == "agent" and t.get("text")]
        if not texts:
            continue
        all_texts += texts
        sessions.append({"id": doc.get("id", f.stem), "profile": doc.get("profile"), "started_at": doc.get("started_at"),
                         **sentence_stats(texts, p)})
    return {"persona": p, "sessions": sessions, "total": sentence_stats(all_texts, p) if all_texts else None}
