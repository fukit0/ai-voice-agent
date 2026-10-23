"""Profil API'si: profilleri listeler ve seçilen profilin STT / LLM / TTS sağlayıcısını çağırır.

Lab ekranları (TTS stüdyosu, STT test, Playground) bu uçları kullanır; ajan aynı sağlayıcı
katmanını (providers/) doğrudan çağırır.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .profiles import Profile, load_profiles
from .providers import ProviderError, ProviderNotReady, get_provider, record_call
from .providers.audio import decode_audio, encode_wav
import time

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = "tr"


class LLMRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    system: str | None = None
    max_tokens: int = Field(default=256, ge=1, le=4096)


def _profile(pid: str) -> Profile:
    profiles = load_profiles()
    if pid not in profiles:
        raise HTTPException(404, {"error": "unknown_profile", "message": f"Profil yok: {pid}",
                                  "available": sorted(profiles)})
    return profiles[pid]


def _provider(profile: Profile, component: str):
    spec = profile.component(component)
    if not spec:
        why = ("tek modelli realtime profil; bileşenler ayrı çağrılamaz" if profile.mode == "realtime"
               else "bu profilde ayrı bir bileşen yok")
        raise HTTPException(400, {"error": "component_unavailable", "profile": profile.id,
                                  "component": component,
                                  "message": f"{profile.id} profilinde {component.upper()} yok: {why}."})
    try:
        return get_provider(spec, component, profile.id)
    except ProviderNotReady as exc:
        raise HTTPException(400, {"error": "provider_not_ready", "profile": profile.id, "component": component,
                                  "message": str(exc), "missing_env": exc.missing_env}) from exc


def _call(profile: Profile, component: str, provider, fn):
    """Sağlayıcıyı çağırır; hata olursa loglayıp 502 döner. (sonuç, süre) verir."""
    t0 = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 — sağlayıcı hatası kullanıcıya anlaşılır dönmeli
        record_call(profile.id, component, provider, time.perf_counter() - t0, ok=False, error=str(exc)[:300])
        raise HTTPException(502, {"error": "provider_failed", "profile": profile.id, "component": component,
                                  "provider": provider.kind, "message": str(exc)}) from exc
    return result, time.perf_counter() - t0


@router.get("")
def list_profiles(check: bool = True) -> list[dict]:
    """Profiller ve durumları. `check=false` yerel servis kontrollerini (Ollama) atlar."""
    return [p.status(check_local=check) for p in load_profiles().values()]


@router.post("/{pid}/tts")
def tts(pid: str, req: TTSRequest) -> Response:
    profile = _profile(pid)
    provider = _provider(profile, "tts")
    result, seconds = _call(profile, "tts", provider, lambda: provider.synthesize(req.text, req.language))
    record_call(profile.id, "tts", provider, seconds, ok=True, chars=len(req.text),
                audio_seconds=round(result.audio_seconds, 2), rtf=round(result.rtf or 0, 3))
    return Response(encode_wav(result.audio, result.sample_rate), media_type="audio/wav", headers={
        "X-Profile": profile.id, "X-Provider": result.provider, "X-Model": result.model,
        "X-Gen-Seconds": f"{result.seconds:.3f}", "X-Audio-Seconds": f"{result.audio_seconds:.3f}",
        "X-RTF": f"{result.rtf or 0:.3f}",
        "Access-Control-Expose-Headers": "X-Profile, X-Provider, X-Model, X-Gen-Seconds, X-Audio-Seconds, X-RTF"})


@router.post("/{pid}/stt")
def stt(pid: str, audio: UploadFile = File(...), language: str = "tr") -> dict:
    profile = _profile(pid)
    provider = _provider(profile, "stt")
    try:
        samples, rate = decode_audio(audio.file.read())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"error": "bad_audio", "message": f"Ses çözülemedi: {exc}"}) from exc
    result, seconds = _call(profile, "stt", provider, lambda: provider.transcribe(samples, rate, language))
    record_call(profile.id, "stt", provider, seconds, ok=True,
                audio_seconds=round(len(samples) / rate, 2), chars=len(result.text))
    return {"profile": profile.id, "provider": result.provider, "model": result.model, "text": result.text,
            "seconds": round(result.seconds, 3), "audio_seconds": round(len(samples) / rate, 2), **result.extra}


@router.post("/{pid}/llm")
def llm(pid: str, req: LLMRequest) -> dict:
    profile = _profile(pid)
    provider = _provider(profile, "llm")
    messages = ([{"role": "system", "content": req.system}] if req.system else []) + [
        {"role": "user", "content": req.prompt}]
    result, seconds = _call(profile, "llm", provider, lambda: provider.complete(messages, max_tokens=req.max_tokens))
    record_call(profile.id, "llm", provider, seconds, ok=True, output_tokens=result.output_tokens)
    return {"profile": profile.id, "provider": result.provider, "model": result.model, "text": result.text,
            "seconds": round(result.seconds, 3), "output_tokens": result.output_tokens, **result.extra}
