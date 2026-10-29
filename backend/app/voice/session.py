"""Sesli konuşma oturumu: taşıma katmanından bağımsız dinle -> anla -> düşün -> konuş döngüsü.

Taşıma (WebRTC, ileride telefon/SIP) 16 kHz mono float32 örnekleri `feed` ile verir, ajanın sesini `out` kanalından
alır. Burada: konuşma bitişi (VAD), STT, LLM, TTS (cümle cümle, ilk cümle hazır olunca çalmaya başlar),
söz kesme (barge-in) ve tur başına gecikme ölçümü bulunur. Anket akışı (flow motoru) core-002'de buraya bağlanır;
core-001 için LLM serbest sohbet eden kısa bir persona ile konuşur.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import stt_runs, trnorm
from ..providers import record_call
from ..providers.audio import resample
from . import phone
from . import sttguard
from .flow import prompt_info
from .silence import SilenceGuard
from .vad import BARGE_FRAMES, BARGE_MARGIN_DB, FRAME, SAMPLE_RATE, Endpointer  # noqa: F401 (BARGE_* diğer modüllerce buradan alınır)

OUT_RATE = 48000
GREETING = "Merhaba, ben Ayşe. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?"
PERSONA = (
    "Sen sahibinden.com adına müşterilerle telefonda konuşan Ayşe adlı sıcak, doğal konuşan bir anket görevlisisin. "
    "Türkçe konuş, kısa yanıt ver (en fazla iki kısa cümle), liste, madde işareti ve emoji kullanma. "
    "Sayıları ve fiyatları rakamla yazabilirsin. Müşteri bir şey sorarsa kısaca yanıtla, sonra nazikçe konuya dön. "
    "Yapay zeka olup olmadığın sorulursa dürüstçe sahibinden.com'un dijital asistanı olduğunu söyle."
)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
# Söz sırası (Smart Turn, PoC sürümü): öğrenilmiş model yok; üç basit katman —
# 1) bitiş sessizliği düğüme göre (kısa cevaplarda 600 ms, açık uçlu cevaplarda 1200 ms),
# 2) transkript tamamlanmamış görünüyorsa ("evet ama", "çünkü", "şey") HOLD_S kadar devam beklenir,
# 3) devam gelirse iki konuşma birleştirilip yeniden çözülür (tek tur).
END_MS_DEFAULT = 600
END_MS_OPEN = 1200
HOLD_S = 1.5
MAX_HOLD_AUDIO_S = 12.0
_TRAILING = re.compile(r"[\s.,;:!?…\-–—\"'’”)]+$")
INCOMPLETE_WORDS = {"ve", "ama", "fakat", "ancak", "çünkü", "yani", "şey", "ki", "ile", "veya", "hem", "ya",
                    "ee", "eee", "ıı", "ııı", "hmm", "mm", "mmm", "hani", "ya da", "bir de"}


def looks_incomplete(text: str) -> bool:
    """Transkript cümle ortasında kesilmiş gibi mi? Muhafazakâr: yalnızca bağlaç/dolgu ile ya da virgül/üç nokta ile biter."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.endswith((",", "…", "...", "-")):
        return True
    words = _TRAILING.sub("", t).split()
    if not words:
        return False
    return words[-1] in INCOMPLETE_WORDS or " ".join(words[-2:]) in INCOMPLETE_WORDS


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def clean_reply(text: str) -> str:
    return _THINK.sub("", text or "").replace("*", "").strip()


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


class VoiceSession:
    def __init__(self, sid: str, profile_id: str, stt, llm, tts, out, send_event: Callable[[dict], None],
                 endpointer: Endpointer | None = None, persona: str = PERSONA, greeting: str = GREETING,
                 flow=None, phone_filter: bool = False, tts_speed: float = 1.0):
        self.tts_speed = tts_speed   # core-005: persona konuşma hızı (TTS destekliyorsa)
        self.sid, self.profile_id = sid, profile_id
        self.stt, self.llm, self.tts, self.out = stt, llm, tts, out
        self.emit = send_event
        self.vad = endpointer or Endpointer()
        self.silence = SilenceGuard()      # core-022: sessiz hat bekçisi
        self.greeting = greeting
        self.flow = flow  # FlowDriver: verilirse konuşmayı senaryo akışı yönetir (aksi halde serbest persona)
        self.phone_filter = phone_filter
        self._in_filter = phone.PhoneFilter(SAMPLE_RATE)
        self.history: list[dict] = [{"role": "system", "content": persona}]
        self.state = "idle"
        self.started_at = datetime.now(timezone.utc)
        self.turns: list[dict] = []
        self.transcript: list[dict] = []
        self.stats = {"frames_in": 0, "seconds_in": 0.0, "utterances": 0, "dropped": 0, "barge_ins": 0,
                      "agent_seconds_out": 0.0, "peak_in_db": -120.0, "holds": 0, "merged": 0,
                      "barge_cut_ms": []}
        self._buf = np.zeros(0, np.float32)
        self._turn_id = 0
        self._barge = 0
        self._barge_t0 = 0.0
        self._held: tuple[np.ndarray, str, dict, float] | None = None
        self._hold_task: asyncio.Task | None = None
        self._synth_done = True
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        out.set_on_drained(self._on_drained)

    # ---- durum ----------------------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.emit({"type": "state", "state": state})

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- giriş ----------------------------------------------------------------------------------
    async def start(self) -> None:
        self._set_state("listening")
        if self.flow is not None:
            reply = self.flow.start()
            self._emit_reply(reply)
            self._apply_endpointing()
            self._spawn(self._speak_turn(" ".join(reply.utterances), turn=self._next_turn(), t_end=time.perf_counter(),
                                         reply=reply))
            return
        self._spawn(self._speak_turn(self.greeting, turn=self._next_turn(), t_end=time.perf_counter(), role_text=True))

    def set_vad(self, cmd: dict) -> None:
        """core-015: ekrandan giriş eşiği / söz kesme ayarı (oturum açıkken, sesi yeniden başlatmadan)."""
        applied = self.vad.configure(threshold_db=cmd.get("db"), barge_frames=cmd.get("barge_frames"),
                                     barge_margin_db=cmd.get("barge_margin_db"), reset_threshold=bool(cmd.get("auto")))
        self.stats["vad"] = applied
        self.emit({"type": "vad_settings", **applied, "server_side": self._server_vad_note(applied)})

    def _server_vad_note(self, applied: dict) -> str | None:
        return None   # kademeli profilde sunucu tarafı VAD yok; ayar tamamen yerel

    def set_phone_filter(self, on: bool) -> None:
        if on != self.phone_filter:
            self.phone_filter = on
            self._in_filter.reset()
        self.emit({"type": "phone_filter", "on": self.phone_filter})

    def _emit_reply(self, reply) -> None:
        for event in reply.events:
            self.emit(event)

    def _apply_endpointing(self) -> None:
        """Bitiş sessizliği, beklenen cevabın türüne göre: açık uçlu cevaplar düşünerek, duraksayarak verilir."""
        kind = None
        if self.flow is not None and self.flow.current is not None:
            kind = self.flow.steps[self.flow.current]["kind"]
        self.vad.set_end_ms(END_MS_OPEN if kind == "OpenText" else END_MS_DEFAULT)

    def feed(self, samples: np.ndarray) -> None:
        """16 kHz mono float32 örnekler (rastgele uzunlukta parçalar)."""
        if self._closed or self.state == "idle":
            return
        samples = samples.astype(np.float32, copy=False)
        if self.phone_filter:
            samples = self._in_filter.process(samples)
        self._buf = np.concatenate([self._buf, samples])
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            self._on_frame(frame)

    def _on_frame(self, frame: np.ndarray) -> None:
        self.stats["frames_in"] += 1
        self.stats["seconds_in"] = round(self.stats["frames_in"] * FRAME / SAMPLE_RATE, 2)
        events = self.vad.feed(frame)
        self.stats["peak_in_db"] = round(max(self.stats["peak_in_db"], self.vad.level), 1)
        if self.state in ("thinking", "speaking"):
            loud = self.vad.level > self.vad.barge_level_db
            if loud and self._barge == 0:
                self._barge_t0 = time.perf_counter()
            self._barge = self._barge + 1 if loud else 0
            if self._barge >= self.vad.barge_frames:
                self._barge_in()
        else:
            self._barge = 0
        for kind, payload in events:
            if kind == "end":
                if self.state in ("thinking", "speaking"):
                    self.stats["dropped"] += 1  # ajan konuşurken kısa gürültü/yankı: söz kesme değil
                    continue
                self.stats["utterances"] += 1
                audio = payload
                if self._held is not None:   # önceki cümle yarımdı: devam geldi, iki konuşmayı birleştir
                    audio = np.concatenate([self._held[0], payload])
                    self._clear_hold()
                    self.stats["merged"] += 1
                self._spawn(self._respond(audio, t_end=time.perf_counter()))
            elif kind == "drop":
                self.stats["dropped"] += 1
                if self.state == "listening":
                    self.silence.note_drop()      # kısa ses denemesi oldu ama duyulmadı: sessizlik bekleme süresi kısalır
        if self.flow is not None and not self.flow.finished and self.flow.current is not None:
            listening = self.state == "listening" and self._held is None and not self._tasks
            if self.silence.tick(listening, self.vad.collecting):
                self._on_silence()

    def _on_silence(self) -> None:
        reply = self.flow.silence()
        self.stats["silences"] = self.stats.get("silences", 0) + 1
        self.emit({"type": "silence", "count": self.flow.silences})
        self._emit_reply(reply)
        self._apply_endpointing()
        if reply.utterances:
            self._spawn(self._speak_turn(" ".join(reply.utterances), turn=self._next_turn(), t_end=time.perf_counter(), reply=reply))

    def _barge_in(self) -> None:
        cut_ms = round((time.perf_counter() - self._barge_t0) * 1000)   # ilk yüksek sesten ajan çıkışının boşaltılmasına
        self._barge = 0
        self._turn_id += 1          # süren tur sonuçları artık atılır
        self.out.flush()
        self._synth_done = True
        self.stats["barge_ins"] += 1
        self.stats["barge_cut_ms"].append(cut_ms)
        self.emit({"type": "barge_in", "cut_ms": cut_ms})
        self._set_state("listening")

    def _next_turn(self) -> int:
        self._turn_id += 1
        return self._turn_id

    def _on_drained(self) -> None:
        if self.state == "speaking" and self._synth_done:
            self._set_state("listening")

    # ---- tur ------------------------------------------------------------------------------------
    async def _respond(self, audio: np.ndarray, t_end: float) -> None:
        turn = self._next_turn()
        self._set_state("thinking")
        rec: dict[str, Any] = {"turn": turn, "user_seconds": round(len(audio) / SAMPLE_RATE, 2),
                               "endpoint_wait_ms": self.vad.end_frames * 20}
        try:
            t0 = time.perf_counter()
            stt_res = await asyncio.to_thread(self.stt.transcribe, audio, SAMPLE_RATE, "tr")
            rec["stt_s"] = round(time.perf_counter() - t0, 3)
            record_call(self.profile_id, "stt", self.stt, rec["stt_s"], ok=True, warm=True,
                        audio_seconds=rec["user_seconds"], chars=len(stt_res.text), source="voice")
            if turn != self._turn_id:
                return
            text = stt_res.text.strip()
            if not text:
                self._set_state("listening")
                return
            ok, reason = sttguard.check(text, stt_res.extra)
            rec["stt_conf"] = stt_res.extra.get("confidence") if stt_res.extra else None
            if not ok:
                # güvenilmez transkript (yabancı yazı, halüsinasyon, düşük güven): cevap sayılmaz, akış tekrar sorar
                rec["stt_rejected"] = reason
                self.stats["stt_rejected"] = self.stats.get("stt_rejected", 0) + 1
                self.emit({"type": "stt_rejected", "text": text, "reason": reason})
                if self.flow is not None:
                    await self._flow_turn(text, turn, t_end, rec, reject=True)
                else:
                    self._set_state("listening")
                return
            if looks_incomplete(text) and len(audio) / SAMPLE_RATE < MAX_HOLD_AUDIO_S:
                self._hold(audio, text, rec, t_end)       # yarım cümle: devam etmesini bekle
                return
            await self._commit(text, turn, t_end, rec)
        except Exception as exc:  # noqa: BLE001 — sağlayıcı hatası oturumu düşürmemeli, kullanıcıya gösterilir
            self.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            if turn == self._turn_id:
                self._set_state("listening")

    async def _commit(self, text: str, turn: int, t_end: float, rec: dict) -> None:
        """Müşterinin tamamlanmış cümlesi: transkripte yaz, cevabı üret, konuş."""
        self._say("user", text)
        if self.flow is not None:
            await self._flow_turn(text, turn, t_end, rec)
            return
        self.history.append({"role": "user", "content": text})
        t1 = time.perf_counter()
        llm_res = await asyncio.to_thread(self.llm.complete, self.history[:1] + self.history[1:][-12:], 120, 0.3)
        rec["llm_s"] = round(time.perf_counter() - t1, 3)
        record_call(self.profile_id, "llm", self.llm, rec["llm_s"], ok=True, warm=True, chars=len(llm_res.text), source="voice")
        if turn != self._turn_id:
            return
        reply = clean_reply(llm_res.text)
        if not reply:
            self._set_state("listening")
            return
        self.history.append({"role": "assistant", "content": reply})
        await self._speak_turn(reply, turn, t_end, rec=rec)

    def _hold(self, audio: np.ndarray, text: str, rec: dict, t_end: float) -> None:
        self._held = (audio, text, rec, t_end)
        self.stats["holds"] += 1
        self._set_state("listening")
        self.emit({"type": "hold", "on": True, "text": text})
        self._hold_task = asyncio.get_running_loop().create_task(self._hold_timeout(self._held))

    def _clear_hold(self) -> None:
        self._held = None
        if self._hold_task is not None:
            self._hold_task.cancel()
            self._hold_task = None
        self.emit({"type": "hold", "on": False})

    async def _hold_timeout(self, held) -> None:
        await asyncio.sleep(HOLD_S)
        if self._held is not held or self._closed:
            return
        _, text, rec, t_end = held
        self._held, self._hold_task = None, None
        self.emit({"type": "hold", "on": False})
        turn = self._next_turn()
        self._set_state("thinking")
        rec["held_s"] = HOLD_S
        try:
            await self._commit(text, turn, t_end, rec)
        except Exception as exc:  # noqa: BLE001
            self.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            if turn == self._turn_id:
                self._set_state("listening")

    async def _flow_turn(self, text: str, turn: int, t_end: float, rec: dict, reject: bool = False) -> None:
        if reject:    # STT geçidi: LLM'e gitmeden "anlaşılmadı" (metin cevap olarak kaydedilmez)
            reply = self.flow.handle_structured({"intent": "unclear", "value": None}, "")
        else:
            reply = await asyncio.to_thread(self.flow.handle, text)
        if reply.llm_s is not None:
            rec["llm_s"] = reply.llm_s
            record_call(self.profile_id, "llm", self.llm, reply.llm_s, ok=True, warm=True, chars=len(text), source="voice")
        if turn != self._turn_id:
            return
        self._emit_reply(reply)
        self._apply_endpointing()
        if not reply.utterances:
            self._set_state("listening")
            return
        await self._speak_turn(" ".join(reply.utterances), turn, t_end, rec=rec, reply=reply)

    async def _speak_turn(self, text: str, turn: int, t_end: float, rec: dict | None = None, role_text: bool = False,
                          reply=None) -> None:
        rec = rec if rec is not None else {"turn": turn, "greeting": True}
        if role_text:
            self.history.append({"role": "assistant", "content": text})
        self._say("agent", text)
        self._synth_done = False
        first_audio: float | None = None
        tts_total = 0.0
        try:
            for sentence in split_sentences(text) or [text]:
                spoken = trnorm.normalize(sentence)
                t0 = time.perf_counter()
                extra = (self.tts_speed,) if self.tts_speed != 1.0 else ()   # hız yalnız değişmişse iletilir
                res = await asyncio.to_thread(self.tts.synthesize, spoken, "tr", *extra)
                dt = time.perf_counter() - t0
                tts_total += dt
                record_call(self.profile_id, "tts", self.tts, dt, ok=True, warm=True, chars=len(spoken), source="voice")
                if turn != self._turn_id:
                    return
                audio = phone.apply(res.audio, res.sample_rate) if self.phone_filter else res.audio
                pcm = to_int16(resample(audio, res.sample_rate, OUT_RATE))
                if first_audio is None:
                    first_audio = time.perf_counter() - t_end
                    rec["tts_first_s"] = round(dt, 3)
                    rec["first_audio_after_end_s"] = round(first_audio, 3)
                    self._set_state("speaking")
                self.stats["agent_seconds_out"] = round(self.stats["agent_seconds_out"] + len(pcm) / OUT_RATE, 2)
                self.out.push(pcm)
        finally:
            if turn == self._turn_id:
                self._synth_done = True
                self.out.mark_end()
                if first_audio is None:
                    self._set_state("listening")
        rec["tts_total_s"] = round(tts_total, 3)
        self.turns.append(rec)
        self.emit({"type": "turn", **rec})
        if self.flow is not None and self.flow.finished and turn == self._turn_id:
            self.emit({"type": "finished", "outcome": self.flow.outcome})

    def _say(self, role: str, text: str) -> None:
        item = {"role": role, "text": text, "t": round((datetime.now(timezone.utc) - self.started_at).total_seconds(), 2)}
        self.transcript.append(item)
        self.emit({"type": "transcript", **item})

    # ---- kapanış --------------------------------------------------------------------------------
    async def close(self) -> Path | None:
        if self._closed:
            return None
        self._closed = True
        if self._hold_task is not None:
            self._hold_task.cancel()
        self._turn_id += 1
        self.out.flush()
        for task in list(self._tasks):
            task.cancel()
        self._set_state("closed")
        folder = stt_runs.data_dir() / "voice-sessions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.sid}.json"
        path.write_text(json.dumps({
            "id": self.sid, "profile": self.profile_id, "started_at": self.started_at.isoformat(timespec="seconds"),
            "stats": self.stats, "turns": self.turns, "transcript": self.transcript,
            "flow": None if self.flow is None else {"scenario": self.flow.sc["key"], "outcome": self.flow.outcome,
                                                    "path": self.flow.path, "answers": self.flow.answers,
                                                    "prompt": prompt_info()},
            "phone_filter": self.phone_filter, "vad": self.vad.settings()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return path
