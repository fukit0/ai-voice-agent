"""TTS stüdyosu (lab-001): ses işleme (seviye normalizasyonu, telefon filtresi) ve oturum / puan kaydı.

Düzen: data/tts-sessions/<id>/{session.json, clips/<clip>.wav, listeners/<slug>.json, ratings.jsonl}
Kör dinleme: her dinleyiciye klipler rastgele sırada ve tek kullanımlık jetonlarla verilir; model adı yalnızca
yönetici görünümünde (session.json) bulunur.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

from .providers.audio import resample

TARGET_RMS_DBFS = -20.0
PEAK_LIMIT = 0.97
PHONE_RATE = 8000
RATING_FIELDS = ("naturalness", "humanlike", "mispronunciation")

_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
_CLIP = re.compile(r"^c[0-9]{3}-[A-Za-z0-9_.-]{1,40}$")
_TOKEN = re.compile(r"^[0-9a-f]{16}$")
_LISTENER = re.compile(r"^[\w .'-]{1,40}$", re.UNICODE)


def rms_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if len(audio) else 0.0
    return -120.0 if rms <= 1e-9 else 20 * float(np.log10(rms))


def normalize_level(audio: np.ndarray, target_dbfs: float = TARGET_RMS_DBFS) -> np.ndarray:
    """Klibi RMS düzeyi hedefe getirir; tepe değer sınırı aşılacaksa kazanç o kadar kısılır."""
    audio = np.asarray(audio, dtype=np.float32)
    current = rms_dbfs(audio)
    if current <= -100.0:
        return audio
    gain = 10 ** ((target_dbfs - current) / 20)
    peak = float(np.max(np.abs(audio)))
    if peak * gain > PEAK_LIMIT:
        gain = PEAK_LIMIT / peak
    return (audio * gain).astype(np.float32)


def phone_filter(audio: np.ndarray, rate: int) -> tuple[np.ndarray, int]:
    """Telefon hattı benzetimi: 300–3400 Hz bant geçiren süzgeç, 8 kHz örnekleme."""
    audio = np.asarray(audio, dtype=np.float32)
    if rate != PHONE_RATE:
        audio = resample(audio, rate, PHONE_RATE)
    sos = butter(4, [300, 3400], btype="bandpass", fs=PHONE_RATE, output="sos")
    return sosfilt(sos, audio).astype(np.float32), PHONE_RATE


def data_dir() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


def sessions_dir() -> Path:
    return data_dir() / "tts-sessions"


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _folder(session_id: str) -> Path | None:
    return sessions_dir() / session_id if _ID.match(session_id) else None


def save_session(session: dict, clips_audio: dict[str, bytes]) -> dict:
    session = {**session, "id": session.get("id") or new_id(),
               "created_at": session.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")}
    folder = sessions_dir() / session["id"]
    (folder / "clips").mkdir(parents=True, exist_ok=True)
    for clip_id, data in clips_audio.items():
        (folder / "clips" / f"{clip_id}.wav").write_bytes(data)
    tmp = folder / "session.json.tmp"  # atomik yazım: izleyen istek yarım dosya görmesin
    tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, folder / "session.json")
    return session


def get_session(session_id: str) -> dict | None:
    folder = _folder(session_id)
    path = folder / "session.json" if folder else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None


def clip_path(session_id: str, clip_id: str) -> Path | None:
    folder = _folder(session_id)
    if folder is None or not _CLIP.match(clip_id):
        return None
    path = folder / "clips" / f"{clip_id}.wav"
    return path if path.is_file() else None


def list_sessions(limit: int = 50) -> list[dict]:
    root = sessions_dir()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted((p for p in root.iterdir() if _ID.match(p.name)), reverse=True)[:limit]:
        s = get_session(folder.name)
        if s:
            ok = [c for c in s["clips"] if c["status"] == "ok"]
            out.append({"id": s["id"], "created_at": s["created_at"], "sentences": len(s["sentences"]),
                        "models": sorted({c["profile"] for c in s["clips"]}), "clips": len(ok),
                        "phone": s.get("phone", False)})
    return out


# ---- kör dinleme -------------------------------------------------------------------------------------------


def valid_listener(name: str) -> bool:
    return bool(_LISTENER.match(name.strip())) if name else False


def _listener_file(folder: Path, listener: str) -> Path:
    slug = hashlib.sha1(listener.strip().casefold().encode("utf-8")).hexdigest()[:16]
    return folder / "listeners" / f"{slug}.json"


def start_listening(session_id: str, listener: str, restart: bool = False) -> dict | None:
    """Dinleyiciye bu oturumun başarılı kliplerini rastgele sırada ve gizli jetonlarla verir (varsa mevcut sıra)."""
    session, folder = get_session(session_id), _folder(session_id)
    if session is None or folder is None:
        return None
    path = _listener_file(folder, listener)
    if path.is_file() and not restart:
        return json.loads(path.read_text(encoding="utf-8"))
    clips = [c for c in session["clips"] if c["status"] == "ok"]
    order = [{"token": secrets.token_hex(8), "clip_id": c["id"]} for c in clips]
    secrets.SystemRandom().shuffle(order)
    assignment = {"listener": listener.strip(), "session": session_id, "order": order}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(assignment, ensure_ascii=False), encoding="utf-8")
    return assignment


def blind_view(session: dict, assignment: dict, ratings: dict[str, dict]) -> dict:
    """Dinleyiciye görünen biçim: model / sağlayıcı yok, yalnızca cümle metni ve verdiği puanlar."""
    by_id = {c["id"]: c for c in session["clips"]}
    items = []
    for i, entry in enumerate(assignment["order"], start=1):
        clip = by_id[entry["clip_id"]]
        items.append({"position": i, "token": entry["token"], "sentence": session["sentences"][clip["sentence_idx"]],
                      "rating": ratings.get(entry["token"])})
    return {"session": session["id"], "listener": assignment["listener"], "items": items,
            "rated": sum(1 for it in items if it["rating"])}


def resolve_token(session_id: str, listener: str, token: str) -> str | None:
    folder = _folder(session_id)
    if folder is None or not _TOKEN.match(token or ""):
        return None
    path = _listener_file(folder, listener)
    if not path.is_file():
        return None
    for entry in json.loads(path.read_text(encoding="utf-8"))["order"]:
        if entry["token"] == token:
            return entry["clip_id"]
    return None


def add_rating(session_id: str, listener: str, token: str, scores: dict, comment: str = "") -> dict:
    folder = _folder(session_id)
    row = {"listener": listener.strip(), "token": token, **scores, "comment": comment.strip()[:500],
           "rated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (folder / "ratings.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def listener_ratings(session_id: str, listener: str) -> dict[str, dict]:
    """Jeton -> son puan (aynı klibe tekrar puan verilirse sonuncusu geçerli)."""
    return {r["token"]: r for r in all_ratings(session_id) if r["listener"].casefold() == listener.strip().casefold()}


def all_ratings(session_id: str) -> list[dict]:
    folder = _folder(session_id)
    path = folder / "ratings.jsonl" if folder else None
    if not path or not path.is_file():
        return []
    latest: dict[tuple, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            latest[(r["listener"].casefold(), r["token"])] = r
    return list(latest.values())


def _resolved_rows(session_id: str) -> list[dict]:
    session, folder = get_session(session_id), _folder(session_id)
    if session is None or folder is None:
        return []
    by_id = {c["id"]: c for c in session["clips"]}
    rows = []
    for r in all_ratings(session_id):
        clip_id = resolve_token(session_id, r["listener"], r["token"])
        clip = by_id.get(clip_id or "")
        if not clip:
            continue
        rows.append({"session": session_id, "listener": r["listener"], "sentence_idx": clip["sentence_idx"] + 1,
                     "sentence": session["sentences"][clip["sentence_idx"]], "profile": clip["profile"],
                     "provider": clip["provider"], "model": clip["model"],
                     "naturalness": r["naturalness"], "humanlike": r["humanlike"],
                     "mispronunciation": r["mispronunciation"], "comment": r.get("comment", ""),
                     "first_audio_s": clip.get("first_audio_seconds"), "rtf": clip.get("rtf"),
                     "rated_at": r["rated_at"]})
    return sorted(rows, key=lambda x: (x["listener"].casefold(), x["sentence_idx"], x["profile"]))


CSV_COLUMNS = ["session", "listener", "sentence_idx", "sentence", "profile", "provider", "model", "naturalness",
               "humanlike", "mispronunciation", "comment", "first_audio_s", "rtf", "rated_at"]


def ratings_csv(session_id: str) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    w.writerows(_resolved_rows(session_id))
    return buf.getvalue()


def summary(session_id: str) -> list[dict]:
    """Modele göre ortalama puanlar (yönetici görünümü)."""
    groups: dict[str, list[dict]] = {}
    for row in _resolved_rows(session_id):
        groups.setdefault(row["profile"], []).append(row)
    out = []
    for profile, rows in sorted(groups.items()):
        n = len(rows)
        out.append({"profile": profile, "model": rows[0]["model"], "ratings": n,
                    **{f: round(sum(r[f] for r in rows) / n, 2) for f in RATING_FIELDS}})
    return out
