"""Persona API'si (core-005): ekrandan persona okuma/kaydetme/sıfırlama, üretilen istem önizlemesi ve cümle uzunluğu raporu."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


class VoiceAssignBody(BaseModel):
    voices: dict[str, str]   # ton -> ses kimliği ("" = atamayı kaldır)


class VoiceAddBody(BaseModel):
    public_owner_id: str = Field(pattern=r"^[A-Za-z0-9]{10,80}$")   # URL yoluna girer: yalnız harf/rakam
    voice_id: str = Field(pattern=r"^[A-Za-z0-9]{10,40}$")
    name: str = Field(min_length=1, max_length=80)


def _eleven_headers() -> dict:
    import os
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise HTTPException(400, {"error": "provider_not_ready", "message": "ELEVENLABS_API_KEY tanımlı değil."})
    return {"xi-api-key": key}


def _voice_row(v: dict, source: str) -> dict:
    labels = v.get("labels") or {}
    return {"voice_id": v.get("voice_id"), "name": v.get("name"), "description": v.get("description") or "",
            "preview_url": v.get("preview_url"), "source": source, "public_owner_id": v.get("public_owner_id"),
            "tags": [x for x in (labels.get("gender") or v.get("gender"), labels.get("age") or v.get("age"),
                                 labels.get("descriptive") or v.get("descriptive"), labels.get("use_case") or v.get("use_case")) if x]}


@router.get("/voices")
def list_voices(search: str = "", library: bool = True) -> dict:
    """ElevenLabs sesleri: hesaptakiler + (istenirse) Türkçe kütüphane sesleri; dinleme klibi, etiketler ve mevcut ton atamaları."""
    from .providers import ProviderError
    from .providers.remote import _get
    headers, rows = _eleven_headers(), []
    try:
        mine = _get("https://api.elevenlabs.io/v2/voices", headers=headers,
                    params={"page_size": 100, **({"search": search} if search else {})}).json().get("voices", [])
        rows += [_voice_row(v, "account") for v in mine]
        if library:
            shared = _get("https://api.elevenlabs.io/v1/shared-voices", headers=headers,
                          params={"language": "tr", "page_size": 40, **({"search": search} if search else {})}).json().get("voices", [])
            have = {r["voice_id"] for r in rows}
            rows += [_voice_row(v, "library") for v in shared if v.get("voice_id") not in have]
    except ProviderError as exc:
        raise HTTPException(502, {"error": "provider_failed", "message": str(exc)}) from exc
    return {"voices": rows, "assigned": TV.voices()}


@router.put("/tones/voices")
def assign_voices(body: VoiceAssignBody) -> dict:
    try:
        TV.set_voices(body.voices)
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_voice_assignment", "message": str(exc)}) from exc
    return {"assigned": TV.voices()}


@router.post("/voices/add")
def add_library_voice(body: VoiceAddBody) -> dict:
    """Kütüphane sesini hesaba ekler (kullanımdan önce gerekebilir; bu çağrı gerçek hesapla doğrulanmadı)."""
    from .providers import ProviderError
    from .providers.remote import _post
    try:
        res = _post(f"https://api.elevenlabs.io/v1/voices/add/{body.public_owner_id}/{body.voice_id}",
                    headers=_eleven_headers(), json={"new_name": body.name[:80]})
    except ProviderError as exc:
        raise HTTPException(502, {"error": "provider_failed", "message": str(exc)}) from exc
    return {"voice_id": res.json().get("voice_id", body.voice_id)}


class LabBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    model: str = Field(pattern=r"^eleven_[a-z0-9_]{2,40}$")
    voice_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{10,40}$")   # boşsa ton/genel ses
    tone: str | None = None
    seed: int | None = 1234
    speed: float = Field(default=1.0, ge=0.7, le=1.3)
    runs: int = Field(default=1, ge=1, le=3)


def _matrix() -> dict:
    import json
    from pathlib import Path
    p = Path(os.environ.get("SVA_ELEVEN_MODELS", TV.ROOT / "config" / "elevenlabs-models.json"))
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"models": []}


@router.get("/model-matrix")
def model_matrix() -> dict:
    """ElevenLabs modelleri: fiyat (1.000 karakter), gecikme notu, ses etiketi desteği, ton kaldıracı. Ölçüm sonuçları ekranda eklenir."""
    return _matrix()


@router.post("/tts-lab")
def tts_lab(body: LabBody) -> dict:
    """Seçilen model + ses + ton ile akışlı üretim; ilk ses süresi, toplam süre, tahmini maliyet ve ses döner (kıyas için)."""
    import numpy as np
    from .providers import ProviderError, remote
    from .providers.audio import encode_wav

    if body.tone is not None and body.tone not in TV.TONE_IDS:
        raise HTTPException(422, {"error": "invalid_tone", "message": f"Ton şunlardan biri olmalı: {', '.join(TV.TONE_IDS)}."})
    headers = _eleven_headers()
    tts = remote.ElevenLabsTTS(body.model, **({"seed": body.seed} if body.seed is not None else {}))
    try:
        voice, req = tts.request(body.text, "tr", body.speed, body.tone, body.voice_id)
    except KeyError as exc:
        raise HTTPException(400, {"error": "no_voice", "message": "Ses seçin veya ELEVENLABS_VOICE_ID tanımlayın."}) from exc
    price = next((m["price_per_1k_usd"] for m in _matrix()["models"] if m["id"] == body.model), None)
    runs = []
    for _ in range(body.runs):
        try:
            first, total, raw = remote._post_stream(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream",
                params={"output_format": f"pcm_{tts.SAMPLE_RATE}"}, headers=headers, json=req)
        except ProviderError as exc:
            raise HTTPException(502, {"error": "provider_failed", "message": str(exc)}) from exc
        audio = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        _seq[0] += 1
        cid = f"lab-{_seq[0]:04d}"
        while len(_clips) >= 40:
            _clips.pop(next(iter(_clips)))
        _clips[cid] = encode_wav(audio, tts.SAMPLE_RATE)
        runs.append({"id": cid, "url": f"/api/persona/tone-demo/{cid}.wav", "first_audio_seconds": round(first, 3),
                     "total_seconds": round(total, 3), "audio_seconds": round(audio.size / tts.SAMPLE_RATE, 2),
                     "acoustics": TV.acoustics(audio, tts.SAMPLE_RATE, body.text)})
    chars = len(req["text"])   # etiket de gönderilen karakterdir
    firsts = sorted(r["first_audio_seconds"] for r in runs)
    return {"model": body.model, "voice_id": voice, "tone": body.tone, "seed": body.seed, "chars": chars,
            "applied": TV.params("elevenlabs", body.model, body.tone), "sent_text": req["text"],
            "price_per_1k_usd": price, "cost_usd": round(chars * price / 1000, 5) if price is not None else None,
            "median_first_audio_seconds": firsts[len(firsts) // 2], "runs": runs}


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
