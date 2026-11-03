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
import threading
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
from .streamaudio import ChunkPipeline
from .. import usage as usage_mod
from .flow import prompt_info
from .silence import SilenceGuard
from .vad import BARGE_FRAMES, BARGE_MARGIN_DB, FRAME, SAMPLE_RATE, BargeTracker, Endpointer  # noqa: F401 (BARGE_* diğer modüllerce buradan alınır)

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


def _describe(provider) -> str | None:
    """Sağlayıcının kısa etiketi (örn. 'elevenlabs:eleven_v4_turbo'); `describe` taşımayan test sahtelerinde None."""
    try:
        return provider.describe()
    except AttributeError:
        return None


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def clean_reply(text: str) -> str:
    return _THINK.sub("", text or "").replace("*", "").strip()


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _billed(stream) -> float:
    try:
        return float(stream.billed_seconds())
    except Exception:  # noqa: BLE001
        return 0.0


class _LiveUtterance:
    """Tek konuşmanın canlı STT akışı + akışa ön ek olarak yollanan bekletilmiş ses (`held`: kimlik karşılaştırması için)."""

    def __init__(self, stream, held):
        self.stream = stream
        self.held = held
        self.samples = 0

    def send(self, audio: np.ndarray) -> None:
        if len(audio) == 0:
            return
        self.samples += len(audio)
        try:
            self.stream.send(to_int16(audio).astype("<i2").tobytes())
        except Exception:  # noqa: BLE001 — gönderim hatası finish()'te görünür ve yedek yola düşülür
            pass

    @property
    def sent_s(self) -> float:
        return self.samples / SAMPLE_RATE


class _TTSStreamHandle:
    """Akışlı TTS okuyucu iş parçacığı ile olay döngüsü arasındaki köprü: kuyruk + durdurma bayrağı."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.q: asyncio.Queue = asyncio.Queue()
        self.cancel = threading.Event()

    def put(self, item: tuple) -> None:
        """İş parçacığından güvenli ekleme; döngü kapanmışsa (oturum bitti) sessizce bırakılır."""
        try:
            self.loop.call_soon_threadsafe(self.q.put_nowait, item)
        except RuntimeError:
            pass

    def stop(self) -> None:
        """Olay döngüsü iş parçacığından: okuyucuya dur de ve bekleyen tüketiciyi hemen uyandır."""
        self.cancel.set()
        self.q.put_nowait(("cancelled", None))


class VoiceSession:
    def __init__(self, sid: str, profile_id: str, stt, llm, tts, out, send_event: Callable[[dict], None],
                 endpointer: Endpointer | None = None, persona: str = PERSONA, greeting: str = GREETING,
                 flow=None, phone_filter: bool = False, tts_speed: float = 1.0, tts_tone: str | None = None):
        self.tts_speed = tts_speed   # core-005: persona konuşma hızı (TTS destekliyorsa)
        import inspect   # ton yalnız `tone` parametresini tanıyan TTS'e iletilir (test sahteleri ve eski sağlayıcılar bozulmaz)
        self.tts_tone = tts_tone if tts_tone and "tone" in inspect.signature(tts.synthesize).parameters else None
        self.sid, self.profile_id = sid, profile_id
        self.stt, self.llm, self.tts, self.out = stt, llm, tts, out
        # Faz 2 (isteğe bağlı): TTS `synthesize_stream` sunuyor VE profilde `streaming: true` ise cümle sesi parça parça çalınır.
        # Diğer tüm profillerde (A1 dahil) eski yol: cümle sesi tamamlanınca itilir.
        self._tts_streaming = callable(getattr(tts, "synthesize_stream", None)) and bool(
            (getattr(tts, "options", None) or {}).get("streaming"))
        self._tts_streams: set[_TTSStreamHandle] = set()
        # Faz 3 (isteğe bağlı): STT `open_stream` sunuyor VE profilde `streaming: true` ise konuşma SÜRERKEN ses canlı bağlantıya
        # akıtılır (konuşma başına bir bağlantı). Toplu `transcribe` her zaman yedektir. Diğer profillerde eski yol.
        self._stt_streaming = callable(getattr(stt, "open_stream", None)) and bool(
            (getattr(stt, "options", None) or {}).get("streaming"))
        self._live: _LiveUtterance | None = None
        self._live_failed: str | None = None     # bu konuşmada canlı akış açılamadıysa nedeni (yedek sayımı için)
        self.emit = send_event
        self.vad = endpointer or Endpointer()
        self.silence = SilenceGuard()      # core-022: sessiz hat bekçisi
        self.usage = usage_mod.UsageMeter()   # eval-003: arama basina kaynak/maliyet sayaci
        self.meta: dict = {}               # eval-001: oturum JSON'una eklenen ek alanlar (örn. {'eval': {...}})
        self.greeting = greeting
        self.flow = flow  # FlowDriver: verilirse konuşmayı senaryo akışı yönetir (aksi halde serbest persona)
        if flow is not None and hasattr(flow, "llm") and not isinstance(flow.llm, usage_mod.MeteredLLM):
            flow.llm = usage_mod.MeteredLLM(flow.llm, self.usage)   # akistaki LLM cagrilari (cevap cikarma) sayilir
        self.phone_filter = phone_filter
        self._in_filter = phone.PhoneFilter(SAMPLE_RATE)
        self.history: list[dict] = [{"role": "system", "content": persona}]
        self.state = "idle"
        self.started_at = datetime.now(timezone.utc)
        self.turns: list[dict] = []
        self.transcript: list[dict] = []
        self.stats = {"frames_in": 0, "seconds_in": 0.0, "utterances": 0, "dropped": 0, "barge_ins": 0,
                      "agent_seconds_out": 0.0, "peak_in_db": -120.0, "holds": 0, "merged": 0,
                      "barge_cut_ms": [], "barge_blocked": 0}
        self._buf = np.zeros(0, np.float32)
        self._turn_id = 0
        self._barge_gate = BargeTracker(self.vad)
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
                                     barge_margin_db=cmd.get("barge_margin_db"), reset_threshold=bool(cmd.get("auto")),
                                     voiced_min=cmd.get("voiced_min"))
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
        if self._live is not None:          # süren konuşmanın çerçevesi (bitiş çerçevesi dahil): canlı STT'ye
            self._live.send(frame)
        self.stats["peak_in_db"] = round(max(self.stats["peak_in_db"], self.vad.level), 1)
        if self.state in ("thinking", "speaking"):
            verdict = self._barge_gate.update(frame, time.perf_counter())
            if verdict == "barge":
                self._barge_t0 = self._barge_gate.t0
                self._barge_in()
            elif verdict == "blocked":      # core-016: konuşma benzeri olmayan yüksek ses (öksürük vb.) ajanı kesmedi
                self.stats["barge_blocked"] += 1
                self.emit({"type": "barge_blocked"})
        else:
            self._barge_gate.reset()
        for kind, payload in events:
            if kind == "start" and self._stt_streaming:
                self._open_live()
            if kind == "end":
                live, self._live = self._live, None
                live_failed, self._live_failed = self._live_failed, None
                if self.state in ("thinking", "speaking"):
                    self.stats["dropped"] += 1  # ajan konuşurken kısa gürültü/yankı: söz kesme değil
                    self._abort_live(live)
                    continue
                self.stats["utterances"] += 1
                audio = payload
                held = self._held
                if self._held is not None:   # önceki cümle yarımdı: devam geldi, iki konuşmayı birleştir
                    audio = np.concatenate([self._held[0], payload])
                    self._clear_hold()
                    self.stats["merged"] += 1
                if live is not None and live.held is not held:
                    # canlı akışın içeriği bu sesle aynı değil (bekletme konuşma sürerken doldu ya da sonradan başladı):
                    # akış kullanılmaz, eski yol (toplu) birebir uygulanır
                    self._abort_live(live)
                    self._count("stt_stream_merge_batch")
                    live = None
                elif live is None and live_failed:   # akış hiç açılamadı: toplu yol = yedek
                    self._count("stt_stream_fallbacks")
                    self.stats.setdefault("stt_stream_fallback_reasons", []).append(live_failed[:160])
                self._spawn(self._respond(audio, t_end=time.perf_counter(), live=live))
            elif kind == "drop":
                self._abort_live(self._live)
                self._live, self._live_failed = None, None
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
        self._stop_tts_streams()
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
    async def _respond(self, audio: np.ndarray, t_end: float, live: _LiveUtterance | None = None) -> None:
        turn = self._next_turn()
        self._set_state("thinking")
        rec: dict[str, Any] = {"turn": turn, "user_seconds": round(len(audio) / SAMPLE_RATE, 2),
                               "endpoint_wait_ms": self.vad.end_frames * 20}
        try:
            t0 = time.perf_counter()
            if self.stt is None:                       # core-010: STT'siz hat, ses doğrudan LLM'e
                await self._respond_audio(audio, turn, t_end, rec)
                return
            if live is not None:
                stt_res = await self._transcribe_live(live, audio, rec, t0)
            else:
                stt_res = await asyncio.to_thread(self.stt.transcribe, audio, SAMPLE_RATE, "tr")
                rec["stt_s"] = round(time.perf_counter() - t0, 3)
                self.usage.add_stt(rec["user_seconds"], rec["stt_s"])
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

    async def _respond_audio(self, audio: np.ndarray, turn: int, t_end: float, rec: dict) -> None:
        if self.flow is None or not getattr(self.llm, "accepts_audio", False):
            raise RuntimeError("STT'siz profil için senaryo ve ses girdili bir LLM gerekir (core-010).")
        rec["audio_in"] = True
        reply = await asyncio.to_thread(self.flow.handle_audio, audio, SAMPLE_RATE)
        if turn != self._turn_id:
            return
        if reply.heard:
            self._say("user", reply.heard)
        await self._flow_reply(reply, reply.heard or "", turn, t_end, rec)

    # ---- akışlı STT (faz 3) ----------------------------------------------------------------------------------------
    def _open_live(self) -> None:
        """VAD konuşma başlangıcı: canlı bağlantıyı aç, ön kaydı (ve bekletilen yarım cümleyi) hemen yolla."""
        if self._live is not None:             # olmamalı (her start'ı end/drop izler); savunma
            self._abort_live(self._live)
            self._live = None
        self._live_failed = None
        stream = None
        try:
            stream = self.stt.open_stream(SAMPLE_RATE, "tr")
            stream.open()
            live = _LiveUtterance(stream, self._held)
            if self._held is not None:         # birleşme olursa akıştaki ses = bekletilen + yeni konuşma (toplu yolla aynı ses)
                live.send(self._held[0])
            live.send(self.vad.pending_audio())
        except Exception as exc:  # noqa: BLE001 — açılamazsa bu konuşma toplu yolla çözülür
            if stream is not None:
                self._abort_live(_LiveUtterance(stream, None))
            self._count("stt_stream_open_failed")
            self._live_failed = f"open_failed: {type(exc).__name__}: {exc}"
            self.emit({"type": "stt_stream", "event": "open_failed", "message": f"{type(exc).__name__}: {exc}"[:200]})
            return
        self._live = live

    def _abort_live(self, live: _LiveUtterance | None) -> None:
        if live is None:
            return
        try:
            live.stream.abort()
        except Exception:  # noqa: BLE001
            pass
        self.usage.add_stt_stream(live.sent_s, 0.0, _billed(live.stream), aborted=True)

    async def _transcribe_live(self, live: _LiveUtterance, audio: np.ndarray, rec: dict, t0: float):
        """Canlı akışın son transkripti; açılamadı / zaman aşımı / boş / STT geçidinden geçmeyen çıktıda konuşmanın TAMAMI
        toplu `transcribe` ile yeniden çözülür (yedek). Hangisi kullanıldıysa sonuç odur; yedek oturum istatistiğine yazılır."""
        reason, res = None, None
        try:
            res = await asyncio.to_thread(live.stream.finish)
            text = (res.text or "").strip()
            if not text:
                reason = "empty"
            else:
                ok, why = sttguard.check(text, res.extra)
                if not ok:
                    reason = f"guard:{why}"
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
        dt = time.perf_counter() - t0
        self.usage.add_stt_stream(live.sent_s, dt, _billed(live.stream))
        record_call(self.profile_id, "stt", self.stt, dt, ok=reason is None, warm=True, audio_seconds=rec["user_seconds"],
                    chars=len(res.text) if res is not None else 0, source="voice", stream=True,
                    **({"error": reason[:300]} if reason else {}))
        rec["stt_stream"] = True
        if reason is None:
            rec["stt_s"] = round(dt, 3)
            return res
        self._count("stt_stream_fallbacks")
        self.stats.setdefault("stt_stream_fallback_reasons", []).append(reason[:160])
        rec["stt_fallback"] = reason[:160]
        t1 = time.perf_counter()
        res = await asyncio.to_thread(self.stt.transcribe, audio, SAMPLE_RATE, "tr")
        batch_s = time.perf_counter() - t1
        self.usage.add_stt(rec["user_seconds"], batch_s)
        record_call(self.profile_id, "stt", self.stt, batch_s, ok=True, warm=True, audio_seconds=rec["user_seconds"],
                    chars=len(res.text), source="voice", fallback=True)
        rec["stt_s"] = round(time.perf_counter() - t0, 3)       # bekleme + yedek: müşterinin gerçekten beklediği süre
        return res

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
        self.usage.add_llm(llm_res, rec["llm_s"])
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
        await self._flow_reply(reply, text, turn, t_end, rec)

    async def _flow_reply(self, reply, text: str, turn: int, t_end: float, rec: dict) -> None:
        free = next((e for e in reply.events if e.get("type") == "free_reply"), None)
        if free is not None:      # ADR 0009 adım 2: konu dışı karşılığın kaynağı ve süresi (docs/serbest-cevap-qwen.md)
            rec["reply_source"] = free.get("source")
            rec["free_reply_s"] = free.get("seconds", 0.0)
            if free.get("reason"):
                rec["free_reply_fallback"] = free["reason"]
            # Thinking ölçümü (docs/serbest-cevap-qwen.md 'Qwen thinking'): açık/kapalı kıyası Ayarlar ekranında bu alanlardan yapılır
            rec["free_reply_thinking"] = bool(free.get("thinking", False))
            rec["free_reply_model"] = free.get("model")
            for src, dst in (("eval_tokens", "free_reply_eval_tokens"), ("think_chars", "free_reply_think_chars"), ("ollama_s", "free_reply_ollama_s")):
                if free.get(src) is not None:
                    rec[dst] = free[src]
        elif any(e.get("type") in ("off_topic", "identity") for e in reply.events):
            rec["reply_source"] = "pool"
        rx = next((e for e in reply.events if e.get("type") == "reaction"), None)
        if rx is not None:        # hum-001: cevaptan sonra söylenen tepki ve kaynağı (pool / ack / fixed_ack / context)
            rec["reaction"] = {"source": rx.get("source"), "bucket": rx.get("bucket")}
        elif any(e.get("type") == "reaction_skipped" for e in reply.events):
            rec["reaction"] = {"source": "skipped", "bucket": None}
        if any(e.get("type") == "fast_path" for e in reply.events):
            rec["fast_path"] = True        # kural yolu: LLM çağrılmadı; llm_s yazılmaz (LLM süre istatistiğini kirletmesin)
        elif reply.llm_s is not None:
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

        def mark_first(tts_first_s: float) -> None:
            nonlocal first_audio
            if first_audio is None:
                first_audio = time.perf_counter() - t_end
                rec["tts_first_s"] = round(tts_first_s, 3)
                rec["first_audio_after_end_s"] = round(first_audio, 3)
                self._set_state("speaking")

        try:
            for sentence in split_sentences(text) or [text]:
                spoken = trnorm.normalize(sentence)
                t0 = time.perf_counter()
                extra = (self.tts_speed,) if self.tts_speed != 1.0 else ()   # hız yalnız değişmişse iletilir
                kw = {"tone": self.tts_tone} if self.tts_tone else {}
                if self._tts_streaming:
                    status, dt = await self._speak_sentence_stream(spoken, extra, kw, turn, t0, mark_first)
                    if status != "fallback":
                        tts_total += dt
                        if turn != self._turn_id:
                            return
                        continue
                    if turn != self._turn_id:   # hata ile söz kesme yarıştı: yedek üretime gerek yok
                        return
                    # akış ilk parçadan önce başarısız: bu cümle eski (akışsız) yolla üretilir; süre ilk denemeyi de kapsar
                res = await asyncio.to_thread(lambda: self.tts.synthesize(spoken, "tr", *extra, **kw))
                dt = time.perf_counter() - t0
                tts_total += dt
                self.usage.add_tts(len(spoken), getattr(res, "audio_seconds", 0.0), dt)
                record_call(self.profile_id, "tts", self.tts, dt, ok=True, warm=True, chars=len(spoken), source="voice")
                if turn != self._turn_id:
                    return
                audio = phone.apply(res.audio, res.sample_rate) if self.phone_filter else res.audio
                pcm = to_int16(resample(audio, res.sample_rate, OUT_RATE))
                mark_first(dt)
                self._push_out(pcm)
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

    def _push_out(self, pcm: np.ndarray) -> None:
        self.stats["agent_seconds_out"] = round(self.stats["agent_seconds_out"] + len(pcm) / OUT_RATE, 2)
        self.out.push(pcm)

    def _stop_tts_streams(self) -> None:
        """Söz kesme / kapanış: süren akışlı TTS isteklerine dur de (okuyucu iş parçacığı bir sonraki parçada HTTP'yi kapatır)."""
        for h in list(self._tts_streams):
            h.stop()

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    async def _speak_sentence_stream(self, spoken: str, extra: tuple, kw: dict, turn: int, t0: float,
                                     mark_first: Callable[[float], None]) -> tuple[str, float]:
        """Bir cümleyi akışlı üretip parçalar geldikçe çalar. Dönüş: (durum, süre).

        durum: "ok" | "cancelled" (söz kesme/kapanış) | "partial" (ilk parçadan SONRA hata: cümle temiz biter, hata fırlatılmaz)
        | "fallback" (ilk parçadan ÖNCE hata ya da boş akış: çağıran aynı cümleyi akışsız `synthesize` ile üretir).
        Ölçüm: tts_first_s = istekten İLK PARÇAYA kadar; kullanım = karakter + alınan toplam örnek süresi."""
        loop = asyncio.get_running_loop()
        h = _TTSStreamHandle(loop)
        tts = self.tts

        def produce() -> None:
            stream = None
            try:
                stream = tts.synthesize_stream(spoken, "tr", *extra, **kw)
                h.put(("rate", stream.sample_rate))
                for chunk in stream:
                    if h.cancel.is_set():
                        break
                    h.put(("chunk", chunk))
                h.put(("end", None))
            except BaseException as exc:  # noqa: BLE001 — tüketiciye iletilir
                h.put(("error", exc))
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass

        self._tts_streams.add(h)
        threading.Thread(target=produce, name="tts-stream", daemon=True).start()
        pipe: ChunkPipeline | None = None
        rate, samples, first_s = 0, 0, None
        status, err = "ok", None
        try:
            while True:
                kind, val = await h.q.get()
                if kind == "rate":
                    rate = int(val)
                    pipe = ChunkPipeline(rate, OUT_RATE, phone_filter=self.phone_filter)
                    continue
                if kind == "cancelled" or turn != self._turn_id:
                    status = "cancelled"
                    break
                if kind == "chunk":
                    if first_s is None:
                        first_s = time.perf_counter() - t0
                    samples += len(val)
                    pcm = pipe.feed(val)
                    if len(pcm):
                        mark_first(first_s)
                        self._push_out(pcm)
                    continue
                if kind == "error":
                    err = val
                if samples == 0:          # hiç ses gelmedi (hata ya da boş gövde): akışsız yola düş
                    status = "fallback"
                    break
                if kind == "error":
                    status = "partial"
                tail = pipe.finish()
                if len(tail):
                    mark_first(first_s)
                    self._push_out(tail)
                break
        finally:
            h.cancel.set()
            self._tts_streams.discard(h)
        dt = time.perf_counter() - t0
        if status == "fallback":
            self._count("tts_stream_fallbacks")
            record_call(self.profile_id, "tts", tts, dt, ok=False, warm=True, chars=len(spoken), source="voice", stream=True,
                        error=(f"{type(err).__name__}: {err}" if err is not None else "bos akis")[:300])
            return status, dt
        audio_s = samples / rate if rate else 0.0
        self.usage.add_tts(len(spoken), audio_s, dt)
        fields = {"stream": True, "first_chunk_s": None if first_s is None else round(first_s, 3)}
        if status == "partial":
            self._count("tts_stream_errors")
            fields["error"] = f"{type(err).__name__}: {err}"[:300]
        if status == "cancelled":
            fields["cancelled"] = True
        record_call(self.profile_id, "tts", tts, dt, ok=status != "partial", warm=True, chars=len(spoken), source="voice", **fields)
        return status, dt

    def _say(self, role: str, text: str) -> None:
        item = {"role": role, "text": text, "t": round((datetime.now(timezone.utc) - self.started_at).total_seconds(), 2)}
        self.transcript.append(item)
        self.emit({"type": "transcript", **item})

    # ---- kapanış --------------------------------------------------------------------------------
    def _usage_report(self) -> dict:
        comps = {}
        for kind, prov in (("stt", self.stt), ("llm", self.llm), ("tts", self.tts)):
            d = _describe(prov)
            comps[kind] = {"provider": d.split(":", 1)[0], "model": d.split(":", 1)[1] if ":" in d else ""} if d else None
        user_s = sum(float(t.get("user_seconds", 0)) for t in self.turns)
        return usage_mod.report(self.usage, duration_s=(datetime.now(timezone.utc) - self.started_at).total_seconds(),
                                user_speech_s=user_s, agent_speech_s=float(self.stats.get("agent_seconds_out", 0)), components=comps)

    async def close(self) -> Path | None:
        if self._closed:
            return None
        self._closed = True
        if self._hold_task is not None:
            self._hold_task.cancel()
        self._turn_id += 1
        self._stop_tts_streams()
        self._abort_live(self._live)
        self._live = None
        self.out.flush()
        for task in list(self._tasks):
            task.cancel()
        self._set_state("closed")
        folder = stt_runs.data_dir() / "voice-sessions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.sid}.json"
        path.write_text(json.dumps({
            "usage": self._usage_report(),
            "id": self.sid, "profile": self.profile_id, "started_at": self.started_at.isoformat(timespec="seconds"),
            # Aramalar ekranı kıyası (lab-004): hangi bileşen, ton ve hızla konuşuldu (profil kimliği tek başına bunu söylemez)
            "stt": _describe(self.stt), "llm": _describe(self.llm), "tts": _describe(self.tts),
            "tts_tone": self.tts_tone, "tts_speed": self.tts_speed,
            # Ölçümün hangi ayarla yapıldığı: ayar sonradan değişse de arama kaydı doğru gruba girer (Aramalar > Kıyas > Profil + hızlı yol)
            "config": {"fast_path": bool(getattr(self.flow, "fast_path", False)) if self.flow else None,
                       "free_reply": (getattr(self.flow, "free_reply", None).describe() if getattr(self.flow, "free_reply", None) is not None
                                      else {"enabled": False}) if self.flow else None,
                       # hum-001 aç/kapa: persona yoksa (realtime) tepki katmanı hiç uygulanmaz -> None
                       "reactions": ({"enabled": bool(getattr(self.flow, "reactions_enabled", True))}
                                     if self.flow and getattr(self.flow, "persona", None) else None),
                       "tts_streaming": self._tts_streaming, "stt_streaming": self._stt_streaming},
            "stats": self.stats, "turns": self.turns, "transcript": self.transcript,
            "flow": None if self.flow is None else {"scenario": self.flow.sc["key"], "outcome": self.flow.outcome,
                                                    "path": self.flow.path, "answers": self.flow.answers,
                                                    "prompt": prompt_info(getattr(self.flow, "prompt_variant", None))},
            "phone_filter": self.phone_filter, "vad": self.vad.settings(), **self.meta}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return path
