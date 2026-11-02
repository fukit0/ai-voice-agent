"""STT test ekranı API'si (lab-002, plan F7.2).

Aynı ses, seçilen STT modellerinden sırayla geçirilir (aynı anda değil: ölçümler birbirini bozmasın);
her model için transkript, işlem süresi, gerçek zamana oranı (RTF) ve referans metin varsa WER döner.
ADR 0001: soğuk model ölçüme alınmaz, o modelin sonucu "cold" durumuyla ve Hazırla uyarısıyla döner.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import stt_runs
from .api_profiles import _call, _provider
from .profiles import load_profiles
from .providers import PROVIDERS, ProviderNotReady, cached, missing_env, provider_key, record_call
from .providers.audio import decode_audio, decode_stereo, encode_wav, rms_dbfs
from .providers.local import MlxWhisperSTT
from .wer import wer

router = APIRouter(prefix="/api/stt", tags=["stt"])
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_AUDIO_SECONDS = 180
SILENT_DBFS = -55.0   # bu seviyenin altındaki kanal STT'ye verilmez: Whisper sessizlikte metin uydurur
SPEAKERS = (("customer", "Müşteri"), ("agent", "Ajan"))


def _stt_models() -> dict[tuple, dict]:
    """Profillerdeki farklı STT tanımları (aynı model birden çok profilde olabilir)."""
    models: dict[tuple, dict] = {}
    for p in load_profiles().values():
        spec = p.component("stt")
        if not spec:
            continue
        key = provider_key(spec)
        if key not in models:
            cls = PROVIDERS.get(spec.get("provider"))
            prov = cached(spec)
            models[key] = {"profile": p.id, "profiles": [], "provider": spec.get("provider"),
                           "model": spec.get("model") or "", "missing_env": missing_env(cls) if cls else [],
                           "warm": bool(prov and prov.is_warm()), "known": cls is not None}
        models[key]["profiles"].append(p.id)
    return models


@router.get("/models")
def list_models() -> list[dict]:
    """Karşılaştırılabilir STT modelleri; `profile` = o modeli kullanan ilk profil (Hazırla buradan yapılır)."""
    return [{**m, "ready": m["known"] and not m["missing_env"]} for m in _stt_models().values()]


@router.post("/compare")
def compare(audio: UploadFile = File(...), profiles: str = Form(...), reference: str = Form(""),
            language: str = Form("tr"), channel: str = Form("mix"), prompt: str = Form("")) -> dict:
    ids = [i for i in dict.fromkeys(x.strip() for x in profiles.split(",")) if i]
    if not ids:
        raise HTTPException(400, {"error": "no_models", "message": "En az bir STT modeli seçin."})
    data = audio.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"error": "audio_too_large", "message": "Ses dosyası 25 MB'tan büyük."})
    if channel == "both":
        return _compare_speakers(audio.filename, data, ids, language)
    try:
        samples, rate = decode_audio(data, channel)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"error": "bad_audio", "message": f"Ses çözülemedi: {exc}"}) from exc
    audio_seconds = len(samples) / rate
    if audio_seconds <= 0:
        raise HTTPException(400, {"error": "bad_audio", "message": "Ses çözülemedi: ses boş (0 sn)."})
    if audio_seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(413, {"error": "audio_too_long",
                                  "message": f"Ses {MAX_AUDIO_SECONDS} sn'den uzun ({audio_seconds:.0f} sn)."})
    all_profiles = load_profiles()
    reference = reference.strip()
    results, seen = [], set()
    for pid in ids:
        profile = all_profiles.get(pid)
        spec = profile.component("stt") if profile else None
        if not spec:
            raise HTTPException(400, {"error": "unknown_stt", "message": f"{pid} profilinde STT yok."})
        if provider_key(spec) in seen:
            continue
        seen.add(provider_key(spec))
        base = {"profile": pid, "provider": spec.get("provider"), "model": spec.get("model") or ""}
        try:
            provider = _provider(profile, "stt")
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            state = "cold" if detail.get("error") == "profile_not_warm" else "not_ready"
            results.append({**base, "status": state, "error": detail.get("message", "")})
            continue
        try:
            result, seconds = _call(profile, "stt", provider, lambda p=provider: p.transcribe(samples, rate, language))
        except HTTPException as exc:
            results.append({**base, "status": "failed", "error": exc.detail.get("message", "") if isinstance(exc.detail, dict) else str(exc.detail)})
            continue
        record_call(pid, "stt", provider, seconds, ok=True, warm=True, audio_seconds=round(audio_seconds, 2),
                    chars=len(result.text), source="stt-test")
        item = {**base, "status": "ok", "model": result.model or base["model"], "text": result.text,
                "seconds": round(result.seconds, 3), "rtf": round(result.seconds / audio_seconds, 3)}
        if reference:
            item.update(wer(reference, result.text).to_dict())
        results.append(item)
        if prompt.strip() and isinstance(provider, MlxWhisperSTT):   # aynı model, alan ipucu ile: etkisini yan yana ölç
            try:
                res2, sec2 = _call(profile, "stt", provider,
                                   lambda p=provider: p.transcribe(samples, rate, language, prompt=prompt.strip()))
            except HTTPException as exc:
                results.append({**base, "model": f"{base['model']} + ipucu", "status": "failed",
                                "error": exc.detail.get("message", "") if isinstance(exc.detail, dict) else str(exc.detail)})
                continue
            item2 = {**base, "status": "ok", "model": f"{res2.model or base['model']} + ipucu", "text": res2.text,
                     "seconds": round(res2.seconds, 3), "rtf": round(res2.seconds / audio_seconds, 3), "prompt": prompt.strip()}
            if reference:
                item2.update(wer(reference, res2.text).to_dict())
            results.append(item2)
    run = stt_runs.save_run({"filename": audio.filename, "audio_seconds": round(audio_seconds, 2),
                             "sample_rate": rate, "reference": reference, "language": language, "channel": channel,
                             "results": results}, encode_wav(samples, rate))
    return run


def _compare_speakers(filename: str | None, data: bytes, ids: list[str], language: str) -> dict:
    """Referans metinsiz transkript: stereo kaydın sol kanalı müşteri, sağ kanalı ajan olarak ayrı ayrı yazıya çevrilir.

    Her model için iki satır (müşteri, ajan) yerine tek sonuç döner: `speakers` altında kanal başına metin/süre/RTF.
    Sessiz kanal STT'ye verilmez (Whisper sessizliğe metin uydurur); `silent: true` ile işaretlenir.
    Kanallar ayrı yazıldığı için konuşma sırası (kim kimden sonra konuştu) bilinmez; yalnızca kanal başına metin verilir."""
    try:
        left, right, rate = decode_stereo(data)
    except ValueError as exc:
        if "tek kanallı" in str(exc):
            raise HTTPException(400, {"error": "not_stereo", "message": f"Müşteri/ajan ayrımı yapılamadı: {exc}."}) from exc
        raise HTTPException(400, {"error": "bad_audio", "message": f"Ses çözülemedi: {exc}"}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"error": "bad_audio", "message": f"Ses çözülemedi: {exc}"}) from exc
    audio_seconds = len(left) / rate
    if audio_seconds <= 0:
        raise HTTPException(400, {"error": "bad_audio", "message": "Ses çözülemedi: ses boş (0 sn)."})
    if audio_seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(413, {"error": "audio_too_long",
                                  "message": f"Ses {MAX_AUDIO_SECONDS} sn'den uzun ({audio_seconds:.0f} sn)."})
    channels = {"customer": left, "agent": right}
    levels = {k: round(rms_dbfs(v), 1) for k, v in channels.items()}
    all_profiles = load_profiles()
    results, seen = [], set()
    for pid in ids:
        profile = all_profiles.get(pid)
        spec = profile.component("stt") if profile else None
        if not spec:
            raise HTTPException(400, {"error": "unknown_stt", "message": f"{pid} profilinde STT yok."})
        if provider_key(spec) in seen:
            continue
        seen.add(provider_key(spec))
        base = {"profile": pid, "provider": spec.get("provider"), "model": spec.get("model") or ""}
        try:
            provider = _provider(profile, "stt")
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            state = "cold" if detail.get("error") == "profile_not_warm" else "not_ready"
            results.append({**base, "status": state, "error": detail.get("message", "")})
            continue
        speakers: dict[str, dict] = {}
        failed = ""
        for key, _label in SPEAKERS:
            if levels[key] < SILENT_DBFS:
                speakers[key] = {"text": "", "silent": True, "level_dbfs": levels[key]}
                continue
            try:
                result, seconds = _call(profile, "stt", provider,
                                        lambda p=provider, x=channels[key]: p.transcribe(x, rate, language))
            except HTTPException as exc:
                failed = exc.detail.get("message", "") if isinstance(exc.detail, dict) else str(exc.detail)
                break
            record_call(pid, "stt", provider, seconds, ok=True, warm=True, audio_seconds=round(audio_seconds, 2),
                        chars=len(result.text), source="stt-test")
            speakers[key] = {"text": result.text, "silent": False, "level_dbfs": levels[key],
                             "seconds": round(result.seconds, 3), "rtf": round(result.seconds / audio_seconds, 3)}
        if failed:
            results.append({**base, "status": "failed", "error": failed})
            continue
        results.append({**base, "status": "ok", "speakers": speakers,
                        "text": "\n".join(f"{label}: {speakers[k]['text'] or '(konuşma yok)'}" for k, label in SPEAKERS)})
    return stt_runs.save_run({"filename": filename, "audio_seconds": round(audio_seconds, 2), "sample_rate": rate,
                              "reference": "", "language": language, "channel": "both", "results": results},
                             encode_wav(np.column_stack([left, right]), rate))


@router.get("/runs")
def runs() -> list[dict]:
    return stt_runs.list_runs()


@router.get("/runs/{run_id}")
def run(run_id: str) -> dict:
    found = stt_runs.get_run(run_id)
    if found is None:
        raise HTTPException(404, {"error": "unknown_run", "message": f"Koşu bulunamadı: {run_id}"})
    return found


@router.get("/runs/{run_id}/audio")
def run_audio(run_id: str) -> FileResponse:
    path = stt_runs.audio_path(run_id)
    if path is None:
        raise HTTPException(404, {"error": "unknown_run", "message": f"Ses bulunamadı: {run_id}"})
    return FileResponse(path, media_type="audio/wav")
