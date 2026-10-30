"""Ton -> ses parametresi eşlemesi (core-005, ADR 0010): Persona'daki ton (samimi/resmî/enerjik/sakin) TTS sağlayıcısının
anlayacağı parametrelere çevrilir.

Eşleme config/tone-voice.json (varsayılan) + data/tone-voice.json (ekrandan düzenleme, derin birleştirilir):
  params.<sağlayıcı>.<model | "default">.<ton> -> {speed, tag, stability, similarity_boost, style, exaggeration, cfg_weight, temperature}
Sağlayıcı ilgilendiği anahtarları okur: EMA yalnız speed; Chatterbox exaggeration/cfg_weight/temperature; ElevenLabs voice_settings
(model ailesine göre) ve v3/v4'te ses etiketi (tag). Sayılar BAŞLANGIÇ tahminidir; dinleyerek kalibre edilir (ton demosu).
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TONE_IDS = ("samimi", "resmi", "enerjik", "sakin")
# Ses atama yuvaları: dört ton + "default" (Genel ses: kendi sesi atanmamış tonlar ve tonsuz çağrılar için)
VOICE_SLOTS = TONE_IDS + ("default",)
# Ses etiketi ([warmly] gibi) destekleyen ElevenLabs model ailesi (resmî belge: v3, v4, v4 Turbo; Flash/Multilingual v2'de belgede yok)
TAG_MODEL = re.compile(r"^eleven_v[34]")
ALLOWED = {"speed", "tag", "stability", "similarity_boost", "style", "use_speaker_boost", "exaggeration", "cfg_weight", "temperature"}


def _default_path() -> Path:
    return Path(os.environ.get("SVA_TONE_VOICE_DEFAULT", ROOT / "config" / "tone-voice.json"))


def _override_path() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "tone-voice.json"


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def defaults() -> dict:
    p = _default_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"params": {}}


def load() -> dict:
    d = defaults()
    p = _override_path()
    if p.is_file():
        try:
            d = _merge(d, json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return d


def validate(mapping: dict) -> list[str]:
    errs: list[str] = []
    for kind, models in (mapping.get("params") or {}).items():
        for model, tones in models.items():
            for tone, vals in tones.items():
                if tone not in TONE_IDS:
                    errs.append(f"{kind}/{model}: bilinmeyen ton '{tone}'.")
                for k, v in vals.items():
                    if k not in ALLOWED:
                        errs.append(f"{kind}/{model}/{tone}: bilinmeyen alan '{k}'.")
                    elif k == "tag":
                        if not isinstance(v, str) or len(v) > 40 or not re.fullmatch(r"\[[\w ,.'-]+\]", v):
                            errs.append(f"{kind}/{model}/{tone}: etiket [kelime] biçiminde olmalı.")
                    elif k == "use_speaker_boost":
                        if not isinstance(v, bool):
                            errs.append(f"{kind}/{model}/{tone}: use_speaker_boost true/false olmalı.")
                    elif isinstance(v, bool) or not isinstance(v, (int, float)):
                        errs.append(f"{kind}/{model}/{tone}: {k} sayı olmalı.")
                    elif k == "speed" and not 0.7 <= v <= 1.3:
                        errs.append(f"{kind}/{model}/{tone}: speed 0,7-1,3 olmalı.")
                    elif k in ("stability", "similarity_boost", "style") and not 0 <= v <= 1:
                        errs.append(f"{kind}/{model}/{tone}: {k} 0-1 olmalı.")
                    elif k == "exaggeration" and not 0 <= v <= 2:
                        errs.append(f"{kind}/{model}/{tone}: exaggeration 0-2 olmalı.")
                    elif k == "cfg_weight" and not 0 <= v <= 1:
                        errs.append(f"{kind}/{model}/{tone}: cfg_weight 0-1 olmalı.")
                    elif k == "temperature" and not 0.05 <= v <= 2:
                        errs.append(f"{kind}/{model}/{tone}: temperature 0,05-2 olmalı.")
    return errs


def voices() -> dict[str, str]:
    """Ekrandan atanan ton (veya "default" = Genel ses) -> ElevenLabs ses kimliği."""
    return {t: v for t, v in (load().get("voices") or {}).items() if t in VOICE_SLOTS and v}


def resolve_voice(tone: str | None) -> str | None:
    """ElevenLabs ses kimliği, öncelik sırasıyla: ton ortam değişkeni (ELEVENLABS_VOICE_ID_<TON>) > ekrandan o tona atanan ses >
    ekrandan atanan Genel ses > ELEVENLABS_VOICE_ID. Ekran ortam değişkeninin genel sesinden önce gelir: Persona'da seçilen ses
    .env'deki eski değere takılmadan profillere hemen etki eder. Hiçbiri yoksa None."""
    assigned = voices()
    return ((tone and os.environ.get(f"ELEVENLABS_VOICE_ID_{tone.upper()}")) or (tone and assigned.get(tone))
            or assigned.get("default") or os.environ.get("ELEVENLABS_VOICE_ID") or None)


def missing_voice_tones() -> list[str]:
    """Hiçbir kaynaktan ses çözülemeyen tonlar (boşsa her ton için bir ses var)."""
    return [t for t in TONE_IDS if not resolve_voice(t)]


def set_voices(assign: dict) -> dict:
    """Ton başına ses ata (boş metin = atamayı kaldır). Kimlik biçimi doğrulanır; diğer ayarlar korunur."""
    bad = [t for t in assign if t not in VOICE_SLOTS]
    bad += [f"{t}={v!r}" for t, v in assign.items() if v and not re.fullmatch(r"[A-Za-z0-9]{10,40}", str(v))]
    if bad:
        raise ValueError("Geçersiz ton/ses kimliği: " + ", ".join(map(str, bad)))
    cur = _read_override()
    merged = {**(cur.get("voices") or {}), **{t: v for t, v in assign.items()}}
    cur["voices"] = {t: v for t, v in merged.items() if v}
    _write_override(cur)
    return load()


def _read_override() -> dict:
    p = _override_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except json.JSONDecodeError:
        return {}


def _write_override(doc: dict) -> None:
    path = _override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def save(mapping: dict) -> dict:
    errs = validate(mapping)
    if errs:
        raise ValueError(" ".join(errs))
    cur = _read_override()   # ses atamaları korunur
    cur["params"] = mapping.get("params", {})
    _write_override(cur)
    return load()


def reset() -> dict:
    """Parametreleri varsayılana döndürür; ekrandan atanan sesler korunur."""
    cur = _read_override()
    cur.pop("params", None)
    if cur:
        _write_override(cur)
    elif _override_path().is_file():
        _override_path().unlink()
    return load()


def params(kind: str, model: str | None, tone: str | None, mapping: dict | None = None) -> dict:
    """Sağlayıcı türü + model + ton için parametre sözlüğü. Model özel kayıt yoksa 'default' kullanılır; bulunamazsa {} (eski davranış)."""
    if not tone:
        return {}
    models = ((mapping or load()).get("params") or {}).get(kind) or {}
    block = models.get(model or "") or models.get("default") or {}
    return dict(block.get(tone) or {})


def uses_tags(model: str | None) -> bool:
    return bool(model and TAG_MODEL.match(model))


def acoustics(audio: np.ndarray, rate: int, text: str = "") -> dict:
    """Klibin yaklaşık akustik özeti (ton farkını sayıyla görmek için): süre, hız (kelime/sn), perde medyanı ve oynaklığı
    (yarım ton std; otokorelasyon tabanlı, YAKLAŞIK) ve ses şiddeti dalgalanması (dB std). Dinlemenin yerini tutmaz."""
    x = np.asarray(audio, dtype=np.float64)
    if x.size < rate // 5:
        return {"seconds": round(x.size / rate, 2)}
    dur = x.size / rate
    frame, hop = int(0.04 * rate), int(0.01 * rate)
    lo, hi = int(rate / 400), int(rate / 70)
    f0s, rms = [], []
    for i in range(0, x.size - frame, hop):
        w = x[i:i + frame]
        e = float(np.sqrt(np.mean(w * w)))
        rms.append(e)
        if e < 0.01:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] / ac[0] > 0.35:
            f0s.append(rate / (lo + k))
    out: dict = {"seconds": round(dur, 2)}
    words = len(re.findall(r"\w+", text))
    if words:
        out["words_per_sec"] = round(words / dur, 2)
    if len(f0s) >= 10:
        f0 = np.array(f0s)
        med = float(np.median(f0))
        out["pitch_median_hz"] = round(med, 1)
        out["pitch_std_semitones"] = round(float(np.std(12 * np.log2(f0 / med))), 2)
    r = np.array(rms)
    r = r[r > 0.01]
    if r.size > 10:
        out["loudness_std_db"] = round(float(np.std(20 * np.log10(r))), 2)
    return out
