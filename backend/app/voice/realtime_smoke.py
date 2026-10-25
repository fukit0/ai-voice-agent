"""Canlı realtime duman testi (core-011): gerçek API anahtarıyla A2/A3 bağdaştırıcılarını sınar.

Bulutta çalıştırılamaz (OpenAI/Google erişimi yok); anahtarı ve ağı olan makinede `scripts/realtime_smoke.py` ile koşulur ve
sonucu evidence/core-011-live-smoke.json'a yazar. Ölçtükleri (her sağlayıcı için):
  1) "AYNEN SÖYLE": ajan verilen metni seslendiriyor mu (ilk sese kadar süre, ses WAV olarak kaydedilir, kendi transkripti
     istenen metne benziyor mu) — Türkçe konuşma kalitesini kulakla değerlendirmek için WAV üretir;
  2) fonksiyon çağrısı güvenilirliği: bilinen müşteri cümleleri için report_answer çağrılıyor mu, değer FlowDriver'ın sıkı
     tip denetiminden (check_value) geçiyor mu, beklenen niyet/değer mi.
"""
from __future__ import annotations

import asyncio
import difflib
import time
import wave
from pathlib import Path

from .. import scenario as S
from .flow import check_value, value_rule
from .realtime import INSTRUCTIONS, TOOL_NAME, RealtimeBackend, parse_tool_args

SAMPLE_TEXT = "Merhaba, ben Elif. Sahibinden.com adına arıyorum. Ahmet Yılmaz ile mi görüşüyorum?"
# (adım, müşteri cümlesi, beklenen niyet, beklenen değer ya da None)
CASES = [
    ("musaitlik", "evet müsaitim", "answer", True),
    ("musaitlik", "hayır şu an değilim", "answer", False),
    ("q2", "sekiz veririm", "answer", 8),
    ("q3_1", "bence on", "answer", 10),
    ("q5", "yaklaşık kırk beş saniye bekledim", "answer", 45),
    ("musaitlik", "şimdi müsait değilim, sonra arayın", "callback", None),
    ("giris", "beni bir daha aramayın", "dnc", None),
    ("q3", "bu ankete katılmak istemiyorum", "refuse", None),
]


async def _collect(backend: RealtimeBackend, until, timeout: float) -> list[dict]:
    got: list[dict] = []

    async def run():
        async for ev in backend.events():
            got.append(ev)
            if until(ev):
                return
    try:
        await asyncio.wait_for(run(), timeout)
    except asyncio.TimeoutError:
        got.append({"type": "timeout"})
    return got


def _save_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


async def run_smoke(backend: RealtimeBackend, out_dir: Path, scenario: str = "anket", timeout: float = 25.0) -> dict:
    steps = S.step_map(S.get(scenario))
    result: dict = {"provider": backend.kind, "model": backend.model, "speak": {}, "tool_calls": [], "errors": []}
    try:
        await backend.connect(INSTRUCTIONS)
        # 1) AYNEN SÖYLE
        t0 = time.perf_counter()
        await backend.speak(SAMPLE_TEXT, value_rule(steps["giris"]))
        seen_audio: list[float] = []

        def until(ev):
            if ev["type"] == "audio" and not seen_audio:
                seen_audio.append(time.perf_counter() - t0)
            return ev["type"] in ("response_done", "timeout", "error")
        evs = await _collect(backend, until, timeout)
        pcm = b"".join(e["pcm"] for e in evs if e["type"] == "audio")
        said = " ".join(e["text"] for e in evs if e["type"] == "agent_text").strip()
        wav = out_dir / f"{backend.kind}.wav"
        if pcm:
            _save_wav(wav, pcm, backend.out_rate)
        result["speak"] = {
            "got_audio": bool(pcm), "first_audio_s": round(seen_audio[0], 3) if seen_audio else None,
            "audio_seconds": round(len(pcm) / 2 / backend.out_rate, 2), "wav": str(wav) if pcm else None,
            "requested": SAMPLE_TEXT, "agent_transcript": said,
            "verbatim_ratio": round(difflib.SequenceMatcher(None, SAMPLE_TEXT.lower(), said.lower()).ratio(), 3) if said else None,
            "timeout": any(e["type"] == "timeout" for e in evs)}
        result["errors"] += [e["message"] for e in evs if e["type"] == "error"]
        # 2) fonksiyon çağrısı güvenilirliği
        for key, text, intent, value in CASES:
            step = steps[key]
            backend.set_answer_rule(value_rule(step))
            t1 = time.perf_counter()
            await backend.inject_user_text(text)
            evs = await _collect(backend, lambda e: e["type"] in ("tool_call", "timeout", "error"), timeout)
            call = next((e for e in evs if e["type"] == "tool_call" and e.get("name") == TOOL_NAME), None)
            row = {"step": key, "utterance": text, "expected": {"intent": intent, "value": value},
                   "called": call is not None, "latency_s": round(time.perf_counter() - t1, 3)}
            if call is not None:
                obj = parse_tool_args(call.get("args"))
                ok, norm = check_value(step, obj) if obj else (False, None)
                row.update({"raw": call.get("args"), "valid_type": ok, "got": {"intent": (obj or {}).get("intent"), "value": norm},
                            "correct": bool(ok and (obj or {}).get("intent") == intent and (value is None or norm == value))})
                await backend.tool_result(call["id"], TOOL_NAME)
            else:
                row.update({"valid_type": False, "correct": False})
            result["errors"] += [e["message"] for e in evs if e["type"] == "error"]
            result["tool_calls"].append(row)
            await _collect(backend, lambda e: e["type"] in ("response_done", "timeout"), 3.0)   # kalan yanıtı boşalt
    except Exception as exc:  # noqa: BLE001 — anahtar/ağ/model hatası sonuç olarak raporlanır
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        await backend.close()
    rows = result["tool_calls"]
    result["summary"] = {"cases": len(rows), "called": sum(r["called"] for r in rows),
                         "valid_type": sum(r["valid_type"] for r in rows), "correct": sum(r["correct"] for r in rows)}
    return result
