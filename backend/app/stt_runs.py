"""STT test koşularının kaydı (lab-002): koşu bilgisi + yüklenen ses, `data/stt-runs/<id>/` altında.

Kaydedilen koşu sonradan listelenir ve aynı sonuçlarla ses dahil yeniden açılır.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def data_dir() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


def runs_dir() -> Path:
    return data_dir() / "stt-runs"


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def save_run(run: dict, wav_bytes: bytes) -> dict:
    run = {**run, "id": run.get("id") or new_id(), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    folder = runs_dir() / run["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(wav_bytes)
    (folder / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return run


def get_run(run_id: str) -> dict | None:
    if not _ID.match(run_id):
        return None
    path = runs_dir() / run_id / "run.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def audio_path(run_id: str) -> Path | None:
    if not _ID.match(run_id):
        return None
    path = runs_dir() / run_id / "audio.wav"
    return path if path.is_file() else None


def list_runs(limit: int = 50) -> list[dict]:
    root = runs_dir()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted((p for p in root.iterdir() if _ID.match(p.name)), reverse=True)[:limit]:
        run = get_run(folder.name)
        if run:
            out.append({"id": run["id"], "created_at": run["created_at"], "filename": run.get("filename"),
                        "audio_seconds": run.get("audio_seconds"), "reference": run.get("reference"),
                        "models": [f"{r['provider']}:{r['model']}" for r in run["results"]],
                        "best_wer": min((r["wer"] for r in run["results"] if r.get("wer") is not None), default=None)})
    return out
