"""TTS stüdyosu API'si (lab-001, plan F7.1): cümle seti × TTS modelleri → klipler, kör dinleme, puanlar, CSV.

Üretim arka plan iş parçacığında sırayla yapılır (ölçümler birbirini bozmasın; Chatterbox gibi yavaş modeller
istek zaman aşımına uğramasın). ADR 0001: soğuk model üretime alınmaz, durumuyla ve Hazırla uyarısıyla döner.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import trnorm
from . import tts_studio as studio
from .api_profiles import _call, _provider
from .profiles import load_profiles
from .providers import PROVIDERS, cached, missing_env, provider_key, record_call
from .providers.audio import encode_wav

router = APIRouter(prefix="/api/tts", tags=["tts-studio"])
MAX_SENTENCES, MAX_CHARS, MAX_MODELS = 30, 400, 8
_busy = threading.Lock()
_active: set[str] = set()  # bu süreçte üretimi süren oturumlar


def _tts_models() -> dict[tuple, dict]:
    """Stüdyoda seçilebilir TTS modelleri: profillerdeki ve stüdyoya özgü farklı TTS tanımları."""
    models: dict[tuple, dict] = {}
    for p in load_profiles(include_studio=True).values():
        spec = p.component("tts")
        if not spec:
            continue
        key = provider_key(spec)
        if key not in models:
            cls = PROVIDERS.get(spec.get("provider"))
            prov = cached(spec)
            models[key] = {"profile": p.id, "profiles": [], "provider": spec.get("provider"),
                           "model": spec.get("model") or "", "missing_env": missing_env(cls) if cls else [],
                           "warm": bool(prov and prov.is_warm()), "known": cls is not None,
                           "studio_only": p.id.startswith("S-")}
        models[key]["profiles"].append(p.id)
    return models


@router.get("/models")
def list_models() -> list[dict]:
    return [{**m, "ready": m["known"] and not m["missing_env"]} for m in _tts_models().values()]


class NormalizeRequest(BaseModel):
    sentences: list[str] = Field(min_length=1, max_length=MAX_SENTENCES)


@router.post("/normalize")
def normalize_preview(req: NormalizeRequest) -> list[dict]:
    """norm-007: TTS'e gidecek metnin önizlemesi (Türkçe sayı / fiyat / tarih / telefon normalizasyonu)."""
    out = []
    for s in req.sentences:
        s = s[:MAX_CHARS * 2]
        out.append({"text": s, "spoken": trnorm.normalize(s), "changes": trnorm.changes(s)})
    return out


class SessionRequest(BaseModel):
    sentences: list[str] = Field(min_length=1)
    profiles: list[str] = Field(min_length=1)
    language: str = "tr"
    phone: bool = False  # telefon turu: 300–3400 Hz süzgeç, 8 kHz
    normalize_text: bool = True  # norm-007: sayı, fiyat, tarih, telefon sentezden önce okunur Türkçeye çevrilir


def _generate(session: dict, pids: list[str]) -> None:
    """Her model × cümle için klip üretir; her kliple birlikte oturum dosyasını günceller."""
    _active.add(session["id"])
    profiles = load_profiles(include_studio=True)
    pending: dict[str, bytes] = {}
    try:
        n = 0
        for pid in pids:
            profile = profiles[pid]
            tts_spec = profile.component("tts")
            for idx, text in enumerate(session["sentences"]):
                n += 1
                clip_id = f"c{n:03d}-{pid}"
                base = {"id": clip_id, "sentence_idx": idx, "profile": pid,
                        "provider": tts_spec.get("provider"), "model": tts_spec.get("model") or ""}
                stop_model = False
                try:
                    provider = _provider(profile, "tts")
                    spoken = session["spoken"][idx]  # normalize kapalıysa cümlenin kendisi
                    result, seconds = _call(profile, "tts", provider,
                                            lambda p=provider, t=spoken: p.synthesize(t, session["language"]))
                    audio, rate = result.audio, result.sample_rate
                    first_audio = float(result.extra.get("first_audio_seconds", result.seconds))
                    if session["phone"]:
                        audio, rate = studio.phone_filter(audio, rate)
                    audio = studio.normalize_level(audio)
                    record_call(pid, "tts", provider, seconds, ok=True, warm=True, chars=len(spoken),
                                audio_seconds=round(result.audio_seconds, 2), rtf=round(result.rtf or 0, 3),
                                first_audio_seconds=round(first_audio, 3), source="tts-studio")
                    pending[clip_id] = encode_wav(audio, rate)
                    session["clips"].append({**base, "status": "ok", "model": result.model or base["model"],
                                             "gen_seconds": round(result.seconds, 3),
                                             "first_audio_seconds": round(first_audio, 3),
                                             "first_audio_measured": "first_audio_seconds" in result.extra,
                                             "audio_seconds": round(len(audio) / rate, 3),
                                             "rtf": round(result.rtf or 0, 3), "sample_rate": rate,
                                             "rms_dbfs": round(studio.rms_dbfs(audio), 2)})
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                    state = {"profile_not_warm": "cold", "provider_not_ready": "not_ready"}.get(
                        detail.get("error"), "failed")
                    session["clips"].append({**base, "status": state, "error": detail.get("message", "")})
                    stop_model = state != "failed"  # soğuk / hazır değil: kalan cümleleri deneme
                session["done"] = n
                studio.save_session(session, pending)
                pending = {}
                if stop_model:
                    n += len(session["sentences"]) - idx - 1
                    session["done"] = n
                    break
        session["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - iş parçacığı sessizce ölmesin
        session["state"], session["error"] = "failed", str(exc)
    finally:
        studio.save_session(session, pending)
        _active.discard(session["id"])
        _busy.release()


@router.post("/sessions", status_code=202)
def create_session(req: SessionRequest) -> dict:
    sentences = [s.strip() for s in req.sentences if s.strip()]
    if not sentences:
        raise HTTPException(400, {"error": "no_sentences", "message": "En az bir cümle girin."})
    if len(sentences) > MAX_SENTENCES or any(len(s) > MAX_CHARS for s in sentences):
        raise HTTPException(400, {"error": "too_long", "message":
                                  f"En çok {MAX_SENTENCES} cümle, her biri en çok {MAX_CHARS} karakter olabilir."})
    ids = list(dict.fromkeys(req.profiles))
    if len(ids) > MAX_MODELS:
        raise HTTPException(400, {"error": "too_many_models", "message": f"En çok {MAX_MODELS} model seçilebilir."})
    profiles = load_profiles(include_studio=True)
    pids, seen = [], set()
    for pid in ids:
        profile = profiles.get(pid)
        spec = profile.component("tts") if profile else None
        if not spec:
            raise HTTPException(400, {"error": "unknown_tts", "message": f"{pid} profilinde TTS yok."})
        if provider_key(spec) not in seen:
            seen.add(provider_key(spec))
            pids.append(pid)
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, {"error": "studio_busy", "message": "Başka bir üretim sürüyor; bitince tekrar deneyin."})
    spoken = [trnorm.normalize(s) for s in sentences] if req.normalize_text else list(sentences)
    session = {"id": studio.new_id(), "language": req.language, "phone": req.phone, "sentences": sentences,
               "text_normalized": req.normalize_text, "spoken": spoken,
               "profiles": pids, "clips": [], "done": 0, "total": len(sentences) * len(pids), "state": "running",
               "normalize": {"target_rms_dbfs": studio.TARGET_RMS_DBFS}}
    session = studio.save_session(session, {})
    threading.Thread(target=_generate, args=(session, pids), daemon=True, name=f"tts-{session['id']}").start()
    return session


def _session(session_id: str) -> dict:
    found = studio.get_session(session_id)
    if found is None:
        raise HTTPException(404, {"error": "unknown_session", "message": f"Oturum bulunamadı: {session_id}"})
    if found.get("state") == "running" and found["id"] not in _active:
        # Backend üretim sırasında durmuş / yeniden başlamış: yarım kalan oturum sonsuza dek "running" kalmasın.
        found = studio.save_session({**found, "state": "interrupted", "error":
                                     "Üretim yarıda kesildi (backend durdu veya yeniden başladı); tamamlanan klipler dinlenebilir."}, {})
    return found


@router.get("/sessions")
def sessions() -> list[dict]:
    return studio.list_sessions()


@router.get("/sessions/{session_id}")
def session(session_id: str) -> dict:
    """Yönetici görünümü: model adları dahil."""
    return _session(session_id)


@router.get("/sessions/{session_id}/clips/{clip_id}/audio")
def clip_audio(session_id: str, clip_id: str) -> FileResponse:
    path = studio.clip_path(session_id, clip_id)
    if path is None:
        raise HTTPException(404, {"error": "unknown_clip", "message": "Klip bulunamadı."})
    return FileResponse(path, media_type="audio/wav")


# ---- dinleyici modu (kör) -----------------------------------------------------------------------------------


class ListenRequest(BaseModel):
    listener: str
    restart: bool = False


def _check_listener(name: str) -> str:
    if not studio.valid_listener(name):
        raise HTTPException(400, {"error": "bad_listener", "message": "Dinleyici adı 1–40 karakter olmalı."})
    return name.strip()


@router.post("/sessions/{session_id}/listen")
def listen(session_id: str, req: ListenRequest) -> dict:
    """Dinleyici için gizli kimlikli, rastgele sıralı klip listesi; model / sağlayıcı bilgisi içermez."""
    s, name = _session(session_id), _check_listener(req.listener)
    if s.get("state") == "running":
        raise HTTPException(409, {"error": "session_running", "message": "Üretim bitmeden dinleme başlatılamaz."})
    assignment = studio.start_listening(session_id, name, restart=req.restart)
    if assignment is None or not assignment["order"]:
        raise HTTPException(400, {"error": "no_clips", "message": "Bu oturumda dinlenecek klip yok."})
    return studio.blind_view(s, assignment, studio.listener_ratings(session_id, name))


@router.get("/sessions/{session_id}/blind/{token}/audio")
def blind_audio(session_id: str, token: str, listener: str) -> FileResponse:
    clip_id = studio.resolve_token(session_id, _check_listener(listener), token)
    path = studio.clip_path(session_id, clip_id) if clip_id else None
    if path is None:
        raise HTTPException(404, {"error": "unknown_clip", "message": "Klip bulunamadı."})
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


class RatingRequest(BaseModel):
    listener: str
    token: str
    naturalness: int = Field(ge=1, le=5)  # 1 yapay … 5 çok doğal
    humanlike: int = Field(ge=1, le=5)  # 1 robotik … 5 gerçek insan gibi
    mispronunciation: int = Field(ge=0, le=5)  # 0 telaffuz hatası yok … 5 çok hatalı
    comment: str = ""


@router.post("/sessions/{session_id}/ratings", status_code=201)
def rate(session_id: str, req: RatingRequest) -> dict:
    _session(session_id)
    name = _check_listener(req.listener)
    if studio.resolve_token(session_id, name, req.token) is None:
        raise HTTPException(404, {"error": "unknown_clip", "message": "Bu dinleyici için böyle bir klip yok."})
    row = studio.add_rating(session_id, name, req.token,
                            {f: getattr(req, f) for f in studio.RATING_FIELDS}, req.comment)
    return {"ok": True, "rated_at": row["rated_at"]}


@router.get("/sessions/{session_id}/ratings.csv")
def ratings_csv(session_id: str) -> Response:
    _session(session_id)
    return Response(studio.ratings_csv(session_id).encode("utf-8-sig"), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="tts-ratings-{session_id}.csv"'})


@router.get("/sessions/{session_id}/summary")
def summary(session_id: str) -> list[dict]:
    _session(session_id)
    return studio.summary(session_id)
