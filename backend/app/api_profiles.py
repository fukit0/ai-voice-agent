"""Profil API'si: profilleri listeler ve seçilen profilin STT / LLM / TTS sağlayıcısını çağırır.

Lab ekranları (TTS stüdyosu, STT test, Playground) bu uçları kullanır; ajan aynı sağlayıcı
katmanını (providers/) doğrudan çağırır.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import warmup
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


def _provider(profile: Profile, component: str, allow_cold: bool = False):
    spec = profile.component(component)
    if not spec:
        why = ("tek modelli realtime profil; bileşenler ayrı çağrılamaz" if profile.mode == "realtime"
               else "bu profilde ayrı bir bileşen yok")
        raise HTTPException(400, {"error": "component_unavailable", "profile": profile.id,
                                  "component": component,
                                  "message": f"{profile.id} profilinde {component.upper()} yok: {why}."})
    try:
        provider = get_provider(spec, component, profile.id)
    except ProviderNotReady as exc:
        raise HTTPException(400, {"error": "provider_not_ready", "profile": profile.id, "component": component,
                                  "message": str(exc), "missing_env": exc.missing_env}) from exc
    if not allow_cold and not provider.is_warm():
        # ADR 0001: ölçümler production koşulunda (model yüklü ve ısınmış) yapılır
        job = warmup.get_job(profile.id)
        if job and job.components.get(component, {}).get("state") == "degraded":
            msg = (f"{profile.id} profilinde {component.upper()} bu bilgisayarda diğer modellerle birlikte sıcak "
                   f"tutulamıyor (bellek çekişmesi); ölçüm production koşulunu temsil etmez.")
        else:
            msg = (f"{profile.id} profili hazır değil ({component.upper()} soğuk). Ölçümler production "
                   f"koşullarında olsun diye önce 'Hazırla' ile modelleri yükleyin.")
        raise HTTPException(409, {"error": "profile_not_warm", "profile": profile.id, "component": component,
                                  "message": msg})
    return provider


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
    out = []
    for p in load_profiles().values():
        status = p.status(check_local=check)
        job = warmup.get_job(p.id)
        status["warmup"] = job.to_dict() if job else None
        out.append(status)
    return out


@router.post("/{pid}/warmup", status_code=202)
def start_warmup(pid: str, keep_others: bool = Query(False), components: str | None = Query(None)) -> dict:
    """Hazırla: profilin modellerini yükler, ısıtır ve sıcak süreyi ölçer (arka planda; GET ile izlenir).

    Varsayılan olarak hedef profilde olmayan modeller bellekten çıkarılır (`keep_others=true` ile kalır).
    `components=stt` gibi bir liste verilirse yalnızca o bileşenler hazırlanır ve hiçbir model çıkarılmaz.
    """
    profile = _profile(pid)
    only = None
    if components:
        only = {c.strip() for c in components.split(",") if c.strip()}
        unknown = only - {"stt", "llm", "tts"}
        if unknown or not any(profile.component(c) for c in only):
            raise HTTPException(400, {"error": "bad_components", "profile": pid,
                                      "message": f"{pid} profilinde hazırlanacak bileşen yok: {components}"})
    if profile.mode != "cascade":
        raise HTTPException(400, {"error": "warmup_unsupported", "profile": pid,
                                  "message": f"{pid} realtime profil; hazırlama Playground'da (lab-003) yapılacak."})
    try:
        job = warmup.start(profile, keep_others=keep_others, only=only)
    except warmup.WarmupBusy as exc:
        raise HTTPException(409, {"error": "warmup_busy", "message": str(exc)}) from exc
    return job.to_dict()


@router.get("/{pid}/warmup")
def get_warmup(pid: str) -> dict:
    _profile(pid)
    job = warmup.get_job(pid)
    if job is None:
        raise HTTPException(404, {"error": "no_warmup", "message": f"{pid} için hazırlama başlatılmadı."})
    return job.to_dict()


@router.post("/{pid}/tts")
def tts(pid: str, req: TTSRequest, allow_cold: bool = Query(False)) -> Response:
    profile = _profile(pid)
    provider = _provider(profile, "tts", allow_cold)
    warm = provider.is_warm()
    result, seconds = _call(profile, "tts", provider, lambda: provider.synthesize(req.text, req.language))
    record_call(profile.id, "tts", provider, seconds, ok=True, warm=warm, chars=len(req.text),
                audio_seconds=round(result.audio_seconds, 2), rtf=round(result.rtf or 0, 3))
    return Response(encode_wav(result.audio, result.sample_rate), media_type="audio/wav", headers={
        "X-Profile": profile.id, "X-Provider": result.provider, "X-Model": result.model,
        "X-Gen-Seconds": f"{result.seconds:.3f}", "X-Audio-Seconds": f"{result.audio_seconds:.3f}",
        "X-RTF": f"{result.rtf or 0:.3f}", "X-Warm": str(warm).lower(),
        "Access-Control-Expose-Headers": "X-Profile, X-Provider, X-Model, X-Gen-Seconds, X-Audio-Seconds, X-RTF, X-Warm"})


@router.post("/{pid}/stt")
def stt(pid: str, audio: UploadFile = File(...), language: str = "tr", allow_cold: bool = Query(False)) -> dict:
    profile = _profile(pid)
    provider = _provider(profile, "stt", allow_cold)
    warm = provider.is_warm()
    try:
        samples, rate = decode_audio(audio.file.read())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"error": "bad_audio", "message": f"Ses çözülemedi: {exc}"}) from exc
    result, seconds = _call(profile, "stt", provider, lambda: provider.transcribe(samples, rate, language))
    record_call(profile.id, "stt", provider, seconds, ok=True, warm=warm,
                audio_seconds=round(len(samples) / rate, 2), chars=len(result.text))
    return {"profile": profile.id, "provider": result.provider, "model": result.model, "text": result.text,
            "seconds": round(result.seconds, 3), "audio_seconds": round(len(samples) / rate, 2), "warm": warm,
            **result.extra}


@router.post("/{pid}/llm")
def llm(pid: str, req: LLMRequest, allow_cold: bool = Query(False)) -> dict:
    profile = _profile(pid)
    provider = _provider(profile, "llm", allow_cold)
    warm = provider.is_warm()
    messages = ([{"role": "system", "content": req.system}] if req.system else []) + [
        {"role": "user", "content": req.prompt}]
    result, seconds = _call(profile, "llm", provider, lambda: provider.complete(messages, max_tokens=req.max_tokens))
    record_call(profile.id, "llm", provider, seconds, ok=True, warm=warm, output_tokens=result.output_tokens)
    return {"profile": profile.id, "provider": result.provider, "model": result.model, "text": result.text,
            "seconds": round(result.seconds, 3), "output_tokens": result.output_tokens, "warm": warm,
            **result.extra}
