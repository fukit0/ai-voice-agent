"""Kıyas düzeneği (eval-001, plan F6.1): kayıtlı persona sesleriyle otomatik test araması.

Fikir: 5 test müşterisi (persona: ses + hız + uzaklık + gürültü + tepki gecikmesi) x 4 yol (tam katılım, ret, geri arama, belirsiz cevaplar)
= 20 arama. Müşterinin cümleleri bir kez ElevenLabs ile üretilip data/eval-sets/clips/ altında WAV olarak saklanır ("kayıtlı sesler"):
koşuda API maliyeti ve ses farkı yoktur, aynı set farklı profillere aynen oynatılır (adil kıyas).
Koşu başsızdır: gerçek VoiceSession (VAD, STT, LLM, TTS, akış motoru) kullanılır; tek fark ajanın sesi hoparlöre değil çöpe gider ve
müşteri sesi mikrofon yerine klipten beslenir. Bitince oturum JSON'u data/voice-sessions/ altına düşer, yani Aramalar ekranında görünür.

Ne ölçülmez (açık): ajan sesi gerçek zamanlı çalınmaz, bu yüzden hoparlör yankısı/kendi sesini duyup kesilme ve ağ gecikmesi yoktur;
müşteri ajanı hiç kesmez (söz kesme testi değildir). Gecikme tanımı canlı oturumla aynıdır (VAD konuşma bitişi -> ajanın ilk sesi).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import persona as persona_mod
from . import scenario as S
from . import stt_runs
from .providers.audio import resample

ROOT = Path(__file__).resolve().parents[2]
RATE = 16000
MAX_TURNS = 80                  # akış döngüye girerse çağrıyı kes
TURN_TIMEOUT_S = 240.0          # bir ajan turunun bitmesi için en fazla bekleme (yerel LLM soğuk kalırsa)
TRAIL_SILENCE_S = 1.6           # cevaptan sonra verilen sessizlik: açık uçlu bitiş eşiği 1,2 sn
PF_MODES = {"off": [False], "on": [True], "both": [False, True]}


def config_dir() -> Path:
    return Path(os.environ.get("SVA_EVAL_CONFIG", ROOT / "config" / "eval"))


def sets_dir() -> Path:
    return stt_runs.data_dir() / "eval-sets"


def runs_dir() -> Path:
    return stt_runs.data_dir() / "eval-runs"


def load_config() -> dict[str, Any]:
    d = config_dir()
    pers = json.loads((d / "personas.json").read_text(encoding="utf-8"))
    paths = json.loads((d / "paths.json").read_text(encoding="utf-8"))
    return {"tts": pers.get("tts") or {"provider": "elevenlabs", "model": "eleven_flash_v2_5"}, "personas": pers["personas"],
            "paths": paths["paths"], "defaults": paths.get("defaults", {})}


# ---------- yol cümleleri ----------
def utterance_for(path: dict, defaults: dict, step_key: str, kind: str, visit: int) -> str:
    """Müşterinin bu adımda söyleyeceği cümle: yolun betiği (liste ise ziyaret sırasına göre), yoksa adım türünün varsayılanı."""
    item = (path.get("script") or {}).get(step_key)
    if isinstance(item, list):
        return item[min(visit, len(item) - 1)]
    if isinstance(item, str):
        return item
    return defaults.get(kind) or "Evet."


def needed_texts(cfg: dict) -> list[str]:
    seen: dict[str, None] = {}
    for p in cfg["paths"]:
        for item in (p.get("script") or {}).values():
            for t in (item if isinstance(item, list) else [item]):
                seen[t] = None
    for t in cfg["defaults"].values():
        seen[t] = None
    return list(seen)


# ---------- kayıtlı sesler ----------
def voices_file() -> Path:
    return sets_dir() / "voices.json"


def assigned_voices() -> dict[str, str]:
    try:
        return json.loads(voices_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def voice_of(persona: dict) -> str | None:
    return persona.get("voice_id") or assigned_voices().get(persona["id"])


def clip_path(voice_id: str, speed: float, text: str) -> Path:
    key = hashlib.sha1(f"{speed:.2f}|{text}".encode("utf-8")).hexdigest()[:14]
    return sets_dir() / "clips" / f"{voice_id}__{key}.wav"


def read_clip(voice_id: str, speed: float, text: str) -> np.ndarray:
    import soundfile as sf
    audio, rate = sf.read(clip_path(voice_id, speed, text), dtype="float32")
    return audio if rate == RATE else resample(audio, rate, RATE)


def set_status(cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    texts = needed_texts(cfg)
    personas, ready = [], True
    for p in cfg["personas"]:
        vid = voice_of(p)
        present = sum(1 for t in texts if vid and clip_path(vid, p["speed"], t).is_file())
        ready &= vid is not None and present == len(texts)
        personas.append({**{k: p[k] for k in ("id", "name", "description", "gender", "age", "speed", "gain_db", "noise_snr_db", "reaction_s")},
                         "voice_id": vid, "clips": present, "clips_needed": len(texts)})
    return {"personas": personas, "paths": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in cfg["paths"]],
            "texts": len(texts), "calls": len(cfg["personas"]) * len(cfg["paths"]), "ready": bool(ready), "build": dict(BUILD)}


def pick_voices(cfg: dict, lister: Callable[[str, str], list[dict]]) -> dict[str, str]:
    """Sesi olmayan her persona için cinsiyet/yaşa uygun, diğer personalardan FARKLI bir ses seçer ve kalıcı yazar."""
    chosen = dict(assigned_voices())
    used = {voice_of(p) for p in cfg["personas"]} - {None}
    for p in cfg["personas"]:
        if voice_of(p):
            continue
        rows = lister(p.get("gender", ""), p.get("age", ""))
        pick = next((r["voice_id"] for r in rows if r.get("voice_id") and r["voice_id"] not in used), None)
        if pick is None:       # yaş süzgeci çok dar kaldıysa yalnız cinsiyetle dene
            pick = next((r["voice_id"] for r in lister(p.get("gender", ""), "") if r.get("voice_id") and r["voice_id"] not in used), None)
        if pick is None:
            raise RuntimeError(f"{p['id']} için uygun ses bulunamadı ({p.get('gender')}/{p.get('age')}); personas.json'a voice_id yazın.")
        chosen[p["id"]] = pick
        used.add(pick)
    sets_dir().mkdir(parents=True, exist_ok=True)
    voices_file().write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")
    return chosen


def eleven_lister(gender: str, age: str) -> list[dict]:
    from .api_persona import list_voices
    return list_voices(search="", library=True, gender=gender, age=age, use_case="", sort="popular", page=0)["voices"]


def default_tts(cfg: dict):
    from .providers import get_provider
    return get_provider(cfg["tts"], "tts", "eval-set")


BUILD: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "error": None}


def build_clips(cfg: dict | None = None, tts=None, lister: Callable[[str, str], list[dict]] | None = None) -> dict[str, int]:
    """Eksik klipleri üretir (var olanlara dokunmaz, yani yeniden çalıştırmak ücretsizdir)."""
    import soundfile as sf
    cfg = cfg or load_config()
    texts = needed_texts(cfg)
    BUILD.update(state="running", done=0, total=len(cfg["personas"]) * len(texts), error=None)
    try:
        pick_voices(cfg, lister or eleven_lister)
        tts = tts or default_tts(cfg)
        made = skipped = 0
        (sets_dir() / "clips").mkdir(parents=True, exist_ok=True)
        for p in cfg["personas"]:
            vid = voice_of(p)
            for t in texts:
                path = clip_path(vid, p["speed"], t)
                if path.is_file():
                    skipped += 1
                else:
                    res = tts.synthesize(t, "tr", p["speed"], voice=vid)
                    audio = resample(res.audio, res.sample_rate, RATE)
                    sf.write(path, audio, RATE, subtype="PCM_16")
                    made += 1
                BUILD["done"] += 1
        BUILD["state"] = "done"
        return {"made": made, "skipped": skipped}
    except Exception as exc:  # noqa: BLE001
        BUILD.update(state="error", error=f"{type(exc).__name__}: {exc}")
        raise


# ---------- persona etkisi (koşu anında; klip önbelleği persona'dan bağımsız kalır) ----------
def apply_persona(clip: np.ndarray, persona: dict, seed: int = 0) -> np.ndarray:
    x = clip * (10 ** (float(persona.get("gain_db", 0)) / 20))
    snr = persona.get("noise_snr_db")
    if snr is not None and len(x):
        rms = float(np.sqrt(np.mean(np.square(x)))) or 1e-4
        noise = np.random.default_rng(seed).normal(0, 1, len(x)).astype(np.float32)
        x = x + noise * (rms / (10 ** (float(snr) / 20)) / (float(np.sqrt(np.mean(np.square(noise)))) or 1.0))
    lead = np.zeros(int(float(persona.get("reaction_s", 0)) * RATE), np.float32)
    return np.concatenate([lead, np.clip(x, -1.0, 1.0)]).astype(np.float32)


# ---------- başsız koşu ----------
class HeadlessOut:
    """Ajanın sesini çöpe atan çıkış: çalma anında bitmiş sayılır (gerçek zamanlı bekleme yok)."""

    def __init__(self) -> None:
        self.cb: Callable[[], None] = lambda: None
        self.seconds = 0.0

    def set_on_drained(self, cb) -> None:
        self.cb = cb

    def push(self, pcm) -> None:
        self.seconds += len(pcm) / 48000

    def flush(self) -> None:
        pass

    def mark_end(self) -> None:
        asyncio.get_running_loop().call_soon(self.cb)


async def _agent_idle(session, timeout: float = TURN_TIMEOUT_S) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not session._tasks and session._held is None and session.state in ("listening", "closed"):
            return True
        await asyncio.sleep(0.01)
    return False


def _summary(doc: dict) -> dict[str, Any]:
    flow = doc.get("flow") or {}
    firsts = sorted(t["first_audio_after_end_s"] for t in doc.get("turns", [])
                    if not t.get("greeting") and t.get("first_audio_after_end_s") is not None)
    p50 = None
    if firsts:
        m = len(firsts) // 2
        p50 = round(firsts[m] if len(firsts) % 2 else (firsts[m - 1] + firsts[m]) / 2, 3)
    answers = flow.get("answers") or []
    return {"outcome": flow.get("outcome"), "answers": len(answers), "unanswered": sum(1 for a in answers if a.get("unanswered")),
            "turns": len(firsts), "first_audio_p50_s": p50}


async def run_call(*, profile_id: str, stt, llm, tts, persona: dict, path: dict, phone_filter: bool, cfg: dict, run_id: str,
                   scenario: str = "anket", clip_loader: Callable[[str, float, str], np.ndarray] = read_clip,
                   max_turns: int = MAX_TURNS) -> dict[str, Any]:
    from .voice.flow import FlowDriver
    from .voice.session import VoiceSession
    cust = persona_mod.load()
    flow = FlowDriver(S.get(scenario), llm, persona_mod.scenario_values(cust), score_policy="clarify", persona=cust)
    sid, events, out = uuid.uuid4().hex[:12], [], HeadlessOut()
    session = VoiceSession(sid, profile_id, stt, llm, tts, out, events.append, flow=flow, phone_filter=phone_filter,
                           persona=persona_mod.system_prompt(cust), greeting=persona_mod.greeting(cust),
                           tts_speed=float(cust.get("speed", 1.0)), tts_tone=cust.get("tone"))
    session.meta = {"eval": {"run_id": run_id, "persona": persona["id"], "path": path["id"], "phone_filter": phone_filter}}
    vid, visits, said = voice_of(persona), Counter(), []
    status = "ok"
    try:
        await session.start()
        for n in range(max_turns):
            if not await _agent_idle(session):
                status = "timeout"
                break
            if flow.finished or flow.current is None:
                break
            key = flow.current
            text = utterance_for(path, cfg["defaults"], key, flow.steps[key]["kind"], visits[key])
            visits[key] += 1
            said.append({"step": key, "text": text})
            audio = apply_persona(clip_loader(vid, persona["speed"], text), persona, seed=n)
            session.feed(np.concatenate([audio, np.zeros(int(TRAIL_SILENCE_S * RATE), np.float32)]))
            await asyncio.sleep(0)
        else:
            status = "max_turns"
        if status == "ok" and not flow.finished:
            status = "not_finished"
        session.meta["eval"]["customer"] = said
    finally:
        path_json = await session.close()
    doc = json.loads(path_json.read_text(encoding="utf-8")) if path_json else {}
    return {"session_id": sid, "status": status, **_summary(doc)}


# ---------- koşu yönetimi ----------
RUNS: dict[str, dict] = {}
_TASKS: dict[str, asyncio.Task] = {}


def _save(run: dict) -> None:
    runs_dir().mkdir(parents=True, exist_ok=True)
    (runs_dir() / f"{run['id']}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")


def plan_calls(cfg: dict, pf_mode: str, personas: list[str] | None, paths: list[str] | None) -> list[dict]:
    ps = [p for p in cfg["personas"] if not personas or p["id"] in personas]
    ts = [t for t in cfg["paths"] if not paths or t["id"] in paths]
    return [{"index": 0, "persona": p["id"], "path": t["id"], "phone_filter": pf, "status": "pending"}
            for pf in PF_MODES[pf_mode] for p in ps for t in ts]


def active_run() -> dict | None:
    return next((r for r in RUNS.values() if r["status"] == "running"), None)


def new_run(profile_id: str, pf_mode: str, cfg: dict, personas: list[str] | None, paths: list[str] | None) -> dict:
    calls = plan_calls(cfg, pf_mode, personas, paths)
    for i, c in enumerate(calls):
        c["index"] = i
    run = {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], "profile": profile_id, "phone_filter": pf_mode,
           "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "finished_at": None, "status": "running",
           "total": len(calls), "done": 0, "calls": calls, "error": None}
    RUNS[run["id"]] = run
    _save(run)
    return run


async def execute(run: dict, cfg: dict, stt, llm, tts, scenario: str = "anket", clip_loader=read_clip) -> None:
    by_p = {p["id"]: p for p in cfg["personas"]}
    by_t = {t["id"]: t for t in cfg["paths"]}
    try:
        for c in run["calls"]:
            if run["status"] == "cancelled":
                break
            c["status"] = "running"
            _save(run)
            try:
                res = await asyncio.wait_for(run_call(profile_id=run["profile"], stt=stt, llm=llm, tts=tts, persona=by_p[c["persona"]],
                                                      path=by_t[c["path"]], phone_filter=c["phone_filter"], cfg=cfg, run_id=run["id"],
                                                      scenario=scenario, clip_loader=clip_loader), timeout=900)
                c.update(res)
            except Exception as exc:  # noqa: BLE001 - bir arama patlarsa diğerleri koşmaya devam eder
                c.update(status="error", error=f"{type(exc).__name__}: {exc}")
            run["done"] += 1
            _save(run)
        if run["status"] == "running":
            run["status"] = "done"
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        run.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(run)


def start(run: dict, cfg: dict, stt, llm, tts, **kw) -> None:
    _TASKS[run["id"]] = asyncio.get_running_loop().create_task(execute(run, cfg, stt, llm, tts, **kw))


def cancel(run_id: str) -> bool:
    run = RUNS.get(run_id)
    if not run or run["status"] != "running":
        return False
    run["status"] = "cancelled"          # sıradaki aramadan önce durur; süren arama biter
    _save(run)
    return True


_RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def get_run(run_id: str) -> dict | None:
    if run_id in RUNS:
        return RUNS[run_id]
    if not _RUN_ID.match(run_id):
        return None
    try:
        return json.loads((runs_dir() / f"{run_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_runs(limit: int = 30) -> list[dict]:
    root = runs_dir()
    rows = {r["id"]: r for r in RUNS.values()}
    if root.is_dir():
        for p in sorted(root.glob("*.json"), reverse=True)[:limit]:
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
                rows.setdefault(r["id"], r)
            except (OSError, ValueError):
                continue
    out = sorted(rows.values(), key=lambda r: r["created_at"], reverse=True)[:limit]
    return [{k: r[k] for k in ("id", "profile", "phone_filter", "created_at", "finished_at", "status", "total", "done")} for r in out]
