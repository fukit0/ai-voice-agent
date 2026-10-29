"""Persona API'si (core-005): ekrandan persona okuma/kaydetme/sıfırlama, üretilen istem önizlemesi ve cümle uzunluğu raporu."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import persona as P
from . import tone_voice as TV

router = APIRouter(prefix="/api/persona", tags=["persona"])


class PersonaBody(BaseModel):
    name: str
    tone: str
    address: str
    max_sentences: int
    max_words_per_sentence: int
    speed: float = 1.0
    acknowledgements: list[str]
    avoid_phrases: list[str]
    extra_rules: str = ""


def _view(p: dict) -> dict:
    return {"persona": p, "defaults": P.defaults(), "options": {"tone": list(P.TONES), "address": list(P.ADDRESS)},
            "prompt": P.system_prompt(p), "greeting": P.greeting(p),
            "preview_ack": [P.ack(p, i) for i in range(len(p["acknowledgements"]))],
            "prompt_stats": P.sentence_stats([P.greeting(p), *p["acknowledgements"]], p)}


@router.get("")
def get_persona() -> dict:
    return _view(P.load())


@router.put("")
def put_persona(body: PersonaBody) -> dict:
    data = body.model_dump()
    problems = P.validate(data)
    if problems:
        raise HTTPException(422, {"error": "invalid_persona", "problems": problems, "message": " ".join(problems)})
    return _view(P.save(data))


@router.post("/preview")
def preview(body: PersonaBody) -> dict:
    """Kaydetmeden istem önizlemesi (ekranda yazarken canlı görünür)."""
    data = body.model_dump()
    problems = P.validate(data)
    return {"problems": problems, **({} if problems else _view(data))}


@router.post("/reset")
def reset_persona() -> dict:
    return _view(P.reset())


@router.get("/report")
def report(limit: int = 20) -> dict:
    return P.report(max(1, min(limit, 100)))


# ---- Ton -> ses (ADR 0010): eşleme tablosu ve aynı cümlenin tonlara göre A/B klipleri ----
DEMO_TEXT = "Merhaba Ahmet Bey, ben Ayşe. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?"
TONE_LABEL = {"samimi": "Samimi", "resmi": "Resmî", "enerjik": "Enerjik", "sakin": "Sakin"}
_clips: dict[str, bytes] = {}   # bellekte en çok 40 klip (demo amaçlı, kalıcı değil)
_seq = [0]


class ToneMapBody(BaseModel):
    params: dict


class ToneDemoBody(BaseModel):
    profile: str
    text: str = DEMO_TEXT
    tones: list[str] = list(TV.TONE_IDS)
    model: str | None = None      # ElevenLabs modelini bu çağrı için değiştirir (flash / v4_turbo / multilingual_v2 / v3 karşılaştırması)
    seed: int | None = 1234       # aynı cümlede tonlar arası farkı sesin rastgeleliğinden ayırmak için
    allow_cold: bool = False


@router.get("/tones")
def tones() -> dict:
    return {"tones": [{"id": t, "label": TONE_LABEL[t], "llm": P.TONES[t]} for t in TV.TONE_IDS],
            "mapping": TV.load(), "defaults": TV.defaults(), "demo_text": DEMO_TEXT}


@router.put("/tones")
def put_tones(body: ToneMapBody) -> dict:
    try:
        TV.save({"params": body.params})
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_tone_map", "message": str(exc)}) from exc
    return tones()


@router.post("/tones/reset")
def reset_tones() -> dict:
    TV.reset()
    return tones()


@router.post("/tone-demo")
def tone_demo(body: ToneDemoBody) -> dict:
    """Aynı cümleyi seçili profilin TTS'iyle her tonda üretir; klip + kullanılan parametreler + akustik özet döner."""
    import inspect

    import numpy as np
    from .api_profiles import _call, _profile, _provider
    from .providers import get_provider
    from .providers.audio import encode_wav

    bad = [t for t in body.tones if t not in TV.TONE_IDS]
    if bad or not body.tones or not body.text.strip() or len(body.text) > 300:
        raise HTTPException(422, {"error": "invalid_tone_demo", "message": "Ton listesi/metin geçersiz (en çok 300 karakter)."})
    profile = _profile(body.profile)
    spec = dict(profile.component("tts") or {})
    if not spec:
        raise HTTPException(400, {"error": "component_unavailable", "message": f"{body.profile} profilinde TTS yok."})
    if body.model:
        spec["model"] = body.model
    if body.seed is not None:
        spec["seed"] = body.seed
    if body.model or body.seed is not None:   # özelleştirilmiş sağlayıcı (aynı anahtar önbellekte kalır)
        provider = get_provider(spec, "tts", profile.id)
    else:
        provider = _provider(profile, "tts", body.allow_cold)
    takes_tone = "tone" in inspect.signature(provider.synthesize).parameters
    clips = []
    for tone in body.tones:
        kw = {"tone": tone} if takes_tone else {}
        res, secs = _call(profile, "tts", provider, lambda kw=kw: provider.synthesize(body.text, "tr", 1.0, **kw))
        _seq[0] += 1
        cid = f"tone-{_seq[0]:04d}-{tone}"
        while len(_clips) >= 40:
            _clips.pop(next(iter(_clips)))
        _clips[cid] = encode_wav(np.asarray(res.audio, dtype=np.float32), res.sample_rate)
        clips.append({"tone": tone, "label": TONE_LABEL[tone], "id": cid, "url": f"/api/persona/tone-demo/{cid}.wav",
                      "seconds": round(secs, 2), "applied": TV.params(provider.kind, provider.model, tone),
                      "acoustics": TV.acoustics(np.asarray(res.audio), res.sample_rate, body.text)})
    return {"profile": body.profile, "provider": provider.kind, "model": provider.model, "seed": body.seed,
            "tag_model": TV.uses_tags(provider.model), "takes_tone": takes_tone, "text": body.text, "clips": clips}


@router.get("/tone-demo/{cid}.wav")
def tone_clip(cid: str):
    from fastapi.responses import Response
    data = _clips.get(cid)
    if data is None:
        raise HTTPException(404, {"error": "unknown_clip", "message": "Klip bulunamadı (sunucu yeniden başladı olabilir)."})
    return Response(data, media_type="audio/wav")
