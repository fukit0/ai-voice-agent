"""Realtime (speech-to-speech) profiller için sesli oturum: A2 OpenAI Realtime, A3 Gemini Live (core-011, ADR 0005).

HİBRİT YÖNTEM. Ses doğrudan realtime modele gider; ama konuşmanın *akışını* modele bırakmayız:
  - model, soruyu "AYNEN SÖYLE" talimatıyla bizim verdiğimiz metinle seslendirir (metni FlowDriver seçer);
  - müşteri konuşunca model yalnızca `report_answer` fonksiyonunu çağırarak cevabı bildirir;
  - bildirilen değeri FlowDriver.handle_structured() aynı sıkı tip denetimiyle doğrular, sonraki adımı o seçer.
Böylece cascade profillerle aynı senaryo, aynı çıkış kuyruğu, aynı cevap sözleşmesi kullanılır ve kıyas adil kalır.

Bu hatta ayrı STT/LLM/TTS yoktur; ölçülebilen tek şey "konuşma bitişinden ajanın ilk sesine" uçtan uca süredir
(kırılımı: cevabı bildirme + metni seslendirme). Arayüz bunu böyle gösterir.

Bağdaştırıcılar WebSocket protokolünü sağlayıcı belgelerine göre konuşur; canlı API ile doğrulama yalnızca anahtarı ve ağ
erişimi olan makinede yapılabilir (bulut testleri FakeRealtime ile çalışır).
"""
from __future__ import annotations

import asyncio
from collections import deque
import base64
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import numpy as np

from .. import stt_runs
from ..providers.audio import resample
from . import phone, sttguard
from .flow import INTENTS, answer_rule
from .session import END_MS_DEFAULT, END_MS_OPEN, OUT_RATE, to_int16
from .silence import SilenceGuard
from .vad import FRAME, SAMPLE_RATE, Endpointer

SPEAK_TIMEOUT_S = 10.0
TOOL_NAME = "report_answer"
TOOL_DESCRIPTION = "Müşterinin az önceki cevabını sisteme bildirir. Müşteri konuştuktan sonra HER ZAMAN bu fonksiyonu çağır."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS), "description": "; ".join(f"{k}: {v}" for k, v in INTENTS.items())},
        "value_json": {"type": "string", "description": 'Cevap değeri, JSON olarak kodlanmış metin: true, 8, 45, "yarın saat on beşte" ya da null. '
                                                        "Yalnızca intent=answer iken dolu; diğer durumlarda null."},
    },
    "required": ["intent", "value_json"],
}
INSTRUCTIONS = (
    "Sen telefonda Türkçe konuşan bir sesli ajansın. Konuşmanın akışını sistem yönetir, sen yönetmezsin.\n"
    "1) Sana 'AYNEN SÖYLE' diye verilen metni kelimesi kelimesine, sıcak ve doğal bir tonla seslendir; kendi cümleni ekleme, "
    "soru uydurma, özetleme, metni değiştirme.\n"
    "2) Müşteri konuştuktan sonra sesli cevap verme; yalnızca report_answer fonksiyonunu çağır.\n"
    "3) Yeni bir talimat gelene kadar sus."
)
OPENAI_URL = "wss://api.openai.com/v1/realtime"
GEMINI_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


def speak_instruction(text: str, rule: str | None = None) -> str:
    msg = f"AYNEN SÖYLE (başka hiçbir şey ekleme): «{text}»"
    if rule:
        msg += f"\nMüşteri cevap verince report_answer çağrısında value kuralı: {rule}."
    return msg


def parse_tool_args(args: dict | str | None) -> dict | None:
    """Fonksiyon çağrısı argümanı -> FlowDriver sözleşmesi {"intent","value"}. Bozuk girdi None döner (anlaşılamadı sayılır)."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    if isinstance(args, dict) and "intent" not in args and isinstance(args.get("answer"), str):
        # Canlı ölçüm (core-011, A2): zorunlu çağrıda model anahtar adını "answer" yazdı; değer geçerli intent ise kabul edilir
        if args["answer"] in INTENTS:
            args = {**args, "intent": args["answer"]}
        else:
            # Canlı ölçüm (5bf3c50abbb4, A2): model seçim değerini "answer" anahtarına yazıp intent'i atladı -> cevap sayılır
            args = {**args, "intent": "answer", "value_json": args.get("value_json", args.get("value", args["answer"]))}
    if not isinstance(args, dict) or "intent" not in args:
        return None
    raw = args.get("value_json", args.get("value"))
    value: Any = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw          # kodlanmamış düz metin (ör. randevu ifadesi): metin adımlarında kabul edilir
    return {"intent": args["intent"], "value": value}


# ---- sağlayıcı bağdaştırıcıları -----------------------------------------------------------------------------------
class RealtimeBackend:
    """Normalize olaylar: audio{pcm}, user_text{text}, agent_text{text}, speech_started, speech_stopped,
    tool_call{id,name,args}, response_done, interrupted, error{message}."""
    kind = "base"
    in_rate = 24000
    out_rate = 24000
    auto_answer = False      # True: konuşma bitince bağdaştırıcı kendisi cevap bildirimi ister (OpenAI)

    def __init__(self, model: str):
        self.model = model
        self.rule: str | None = None

    def set_answer_rule(self, rule: str | None) -> None:
        self.rule = rule

    local_turns = False    # core-018: True ise tur sınırlarını sunucu değil yerel VAD belirler (commit + cevap isteği)

    async def commit_audio(self) -> None: ...
    async def clear_audio(self) -> None: ...

    async def connect(self, instructions: str) -> None: raise NotImplementedError
    async def send_audio(self, pcm16: bytes) -> None: raise NotImplementedError
    async def request_answer(self) -> None: ...
    async def speak(self, text: str, rule: str | None) -> None: raise NotImplementedError
    async def tool_result(self, call_id: str, name: str) -> None: ...
    async def interrupt(self) -> None: ...
    async def inject_user_text(self, text: str) -> None:
        """Duman testi: müşteri sesi yerine metin gönderir (canlı API'de ses dosyası gerektirmeden fonksiyon çağrısı güvenilirliği)."""
        raise NotImplementedError
    async def close(self) -> None: ...
    def events(self) -> AsyncIterator[dict]: raise NotImplementedError


class _WsBackend(RealtimeBackend):
    env = ""

    def __init__(self, model: str):
        super().__init__(model)
        self.ws = None
        self._q: asyncio.Queue[dict] = asyncio.Queue()
        self._reader: asyncio.Task | None = None

    def _key(self) -> str:
        key = os.environ.get(self.env, "")
        if not key:
            raise RuntimeError(f"{self.env} tanımlı değil")
        return key

    async def _send(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj, ensure_ascii=False))

    async def events(self):
        while True:
            ev = await self._q.get()
            if ev.get("type") == "_closed":
                return
            yield ev

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._q.put_nowait({"type": "_closed"})

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                for ev in self.parse(json.loads(raw)):
                    self._q.put_nowait(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — bağlantı koptu: oturuma hata olarak bildirilir
            self._q.put_nowait({"type": "error", "message": f"{self.kind} bağlantısı koptu: {type(exc).__name__}: {exc}"})
        finally:
            self._q.put_nowait({"type": "_closed"})

    def parse(self, msg: dict) -> list[dict]: raise NotImplementedError


class OpenAIRealtime(_WsBackend):
    """OpenAI Realtime (WebSocket). Ses: 24 kHz PCM16. Sunucu VAD'ı otomatik cevap üretmez (create_response=false):
    konuşma bitince biz yalnızca-fonksiyon-çağrısı cevabı isteriz, sonra metni seslendirtiriz."""
    kind = "openai_realtime"
    env = "OPENAI_API_KEY"
    in_rate = out_rate = 24000
    auto_answer = True

    def __init__(self, model: str, local_turns: bool = True):
        super().__init__(model)
        self.local_turns = local_turns      # profilde `local_turns: false` ile sunucu VAD'ına dönülebilir
        self._seen_calls: set[str] = set()
        self.threshold: float | None = None   # core-015: server_vad.threshold (0-1); None = sunucu varsayılanı
        self._active = False                  # aktif (üretilen) yanıt var mı: yoksa response.cancel "Cancellation failed" hatası verir

    @staticmethod
    def threshold_for_db(db: float) -> float:
        """dBFS -> server_vad.threshold: -60..-20 dBFS aralığı 0,2..0,9'a doğrusal eşlenir (sezgisel; ölçülmedi)."""
        return round(max(0.2, min(0.9, 0.2 + (db + 60.0) / 40.0 * 0.7)), 2)

    def set_sensitivity(self, db: float) -> float:
        self.threshold = self.threshold_for_db(db)
        return self.threshold

    async def commit_audio(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"})

    async def clear_audio(self) -> None:
        await self._send({"type": "input_audio_buffer.clear"})

    async def apply_sensitivity(self) -> None:
        if self.ws is not None and self.threshold is not None and not self.local_turns:
            await self._send({"type": "session.update", "session": {"type": "realtime", "audio": {"input": {
                "turn_detection": {"type": "server_vad", "threshold": self.threshold, "create_response": False,
                                   "interrupt_response": False, "silence_duration_ms": 500}}}}})

    async def connect(self, instructions: str) -> None:
        import websockets
        self.ws = await websockets.connect(f"{OPENAI_URL}?model={self.model}",
                                           additional_headers={"Authorization": f"Bearer {self._key()}"})
        self._reader = asyncio.get_running_loop().create_task(self._read_loop())
        await self._send({"type": "session.update", "session": {
            "type": "realtime", "model": self.model, "instructions": instructions, "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": 24000},
                          # prompt KALDIRILDI: canlı A2 oturumu eaee33b00412'de model sessiz/gürültülü sesi prompt metniyle yazıya döktü
                          "transcription": {"model": "gpt-4o-mini-transcribe", "language": "tr"},
                          # local_turns: tur sınırlarını yerel VAD verir (commit + cevap isteği); sunucu VAD'ı hoparlör yankısında
                          # ve gürültüde sahte tur açıyordu (core-018)
                          "turn_detection": None if self.local_turns else {
                              "type": "server_vad", "create_response": False, "interrupt_response": False, "silence_duration_ms": 500,
                              **({"threshold": self.threshold} if self.threshold is not None else {})}},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "marin"}},
            "tools": [{"type": "function", "name": TOOL_NAME, "description": TOOL_DESCRIPTION, "parameters": TOOL_PARAMETERS}],
            "tool_choice": "none"}})

    async def send_audio(self, pcm16: bytes) -> None:
        await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm16).decode()})

    async def request_answer(self) -> None:
        """Müşteri konuştu: ses çıkarmadan yalnızca report_answer çağrısı iste."""
        instr = "Müşterinin az önceki cevabını report_answer fonksiyonuyla bildir."
        if self.rule:
            instr += f" value kuralı: {self.rule}."
        await self._send({"type": "response.create", "response": {
            "output_modalities": ["text"], "instructions": instr,
            "tool_choice": {"type": "function", "name": TOOL_NAME}}})

    async def tool_result(self, call_id: str, name: str) -> None:
        await self._send({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps({"ok": True})}})

    async def speak(self, text: str, rule: str | None) -> None:
        self.rule = rule
        await self._send({"type": "response.create", "response": {
            "output_modalities": ["audio"], "instructions": speak_instruction(text), "tool_choice": "none"}})

    async def interrupt(self) -> None:
        if self._active:     # aktif yanıt yokken response.cancel "Cancellation failed: no active response found" hatası verir
            await self._send({"type": "response.cancel"})

    async def inject_user_text(self, text: str) -> None:
        await self._send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
        await self.request_answer()

    def parse(self, msg: dict) -> list[dict]:
        t = msg.get("type", "")
        if t in ("response.output_audio.delta", "response.audio.delta"):
            return [{"type": "audio", "pcm": base64.b64decode(msg.get("delta", ""))}]
        if t in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
            return [{"type": "agent_text", "text": msg.get("transcript", "")}]
        if t == "conversation.item.input_audio_transcription.completed":
            return [{"type": "user_text", "text": msg.get("transcript", "")}]
        if t == "input_audio_buffer.speech_started":
            return [{"type": "speech_started"}]
        if t == "input_audio_buffer.speech_stopped":
            return [{"type": "speech_stopped"}]
        if t == "response.function_call_arguments.done":
            cid = msg.get("call_id", "")
            if cid in self._seen_calls:
                return []
            self._seen_calls.add(cid)
            return [{"type": "tool_call", "id": cid, "name": msg.get("name", ""), "args": msg.get("arguments", "")}]
        if t == "response.created":
            self._active = True
            return []
        if t == "response.done":
            self._active = False
            return [{"type": "response_done"}]
        if t == "error":
            err = msg.get("error") or {}
            message = err.get("message", "OpenAI Realtime hatası")
            if err.get("code") == "response_cancel_not_active" or "no active response" in message:
                return []    # zararsız yarış: yanıt biz iptal etmeden bitmişti
            return [{"type": "error", "message": message}]
        return []


class GeminiLive(_WsBackend):
    """Gemini Live (WebSocket). Girdi 16 kHz, çıktı 24 kHz PCM16. Sunucu VAD'ı konuşma bitince kendi cevap turunu başlatır;
    sistem talimatı bu turda yalnızca report_answer çağırmasını söyler. Metni seslendirtmek için realtimeInput.text kullanılır
    (clientContent mevcut üretimi keser)."""
    kind = "gemini_live"
    env = "GEMINI_API_KEY"
    in_rate, out_rate = 16000, 24000

    async def connect(self, instructions: str) -> None:
        import websockets
        self.ws = await websockets.connect(f"{GEMINI_URL}?key={self._key()}")
        self._reader = asyncio.get_running_loop().create_task(self._read_loop())
        await self._send({"setup": {
            "model": f"models/{self.model}",
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"languageCode": "tr-TR",
                                                  "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}},
            "systemInstruction": {"parts": [{"text": instructions}]},
            "tools": [{"functionDeclarations": [{"name": TOOL_NAME, "description": TOOL_DESCRIPTION,
                                                 "parameters": TOOL_PARAMETERS}]}],
            "inputAudioTranscription": {}, "outputAudioTranscription": {},
            "realtimeInputConfig": {"automaticActivityDetection": {"disabled": False},
                                    "activityHandling": "START_OF_ACTIVITY_INTERRUPTS"}}})

    async def send_audio(self, pcm16: bytes) -> None:
        await self._send({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000",
                                                      "data": base64.b64encode(pcm16).decode()}}})

    async def tool_result(self, call_id: str, name: str) -> None:
        await self._send({"toolResponse": {"functionResponses": [{"id": call_id, "name": name, "response": {"ok": True}}]}})

    async def speak(self, text: str, rule: str | None) -> None:
        self.rule = rule
        await self._send({"realtimeInput": {"text": speak_instruction(text, rule)}})

    async def inject_user_text(self, text: str) -> None:
        msg = f"MÜŞTERİ DEDİ Kİ: «{text}»"
        if self.rule:
            msg += f"\nreport_answer value kuralı: {self.rule}."
        await self._send({"realtimeInput": {"text": msg}})

    def parse(self, msg: dict) -> list[dict]:
        out: list[dict] = []
        sc = msg.get("serverContent") or {}
        for part in ((sc.get("modelTurn") or {}).get("parts") or []):
            data = (part.get("inlineData") or {}).get("data")
            if data:
                out.append({"type": "audio", "pcm": base64.b64decode(data)})
        if (sc.get("inputTranscription") or {}).get("text"):
            out.append({"type": "user_text", "text": sc["inputTranscription"]["text"]})
        if (sc.get("outputTranscription") or {}).get("text"):
            out.append({"type": "agent_text", "text": sc["outputTranscription"]["text"]})
        if sc.get("interrupted"):
            out.append({"type": "interrupted"})
        if sc.get("turnComplete"):
            out.append({"type": "response_done"})
        for call in ((msg.get("toolCall") or {}).get("functionCalls") or []):
            out.append({"type": "tool_call", "id": call.get("id", ""), "name": call.get("name", ""), "args": call.get("args") or {}})
        return out


class FakeRealtime(RealtimeBackend):
    """Modelsiz, ağsız sahte realtime sağlayıcı (SVA_FAKE_PROVIDERS=1 ya da testler). Gelen sesi basit enerji eşiğiyle
    konuşma olarak algılar; konuşma bitince betikli cevabı fonksiyon çağrısı olarak bildirir; metni sinüs sesiyle 'seslendirir'."""
    kind = "fake_realtime"
    in_rate = out_rate = 24000

    def __init__(self, model: str = "fake", script: list[dict] | None = None):
        super().__init__(model)
        self.script = list(script) if script is not None else None
        self.default = {"intent": "answer", "value_json": "true"}
        self.spoken: list[tuple[str, str | None]] = []
        self.results: list[str] = []
        self.interrupts = 0
        self.instructions = ""
        self._q: asyncio.Queue[dict] = asyncio.Queue()
        self._loud = 0
        self._quiet = 0
        self._in_speech = False
        self._n_calls = 0

    async def connect(self, instructions: str) -> None:
        self.instructions = instructions

    async def events(self):
        while True:
            ev = await self._q.get()
            if ev.get("type") == "_closed":
                return
            yield ev

    async def close(self) -> None:
        self._q.put_nowait({"type": "_closed"})

    async def send_audio(self, pcm16: bytes) -> None:
        a = np.frombuffer(pcm16, np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(a * a))) if len(a) else 0.0
        if rms > 0.02:
            self._loud += 1
            self._quiet = 0
            if self._loud >= 3 and not self._in_speech:
                self._in_speech = True
                self._q.put_nowait({"type": "speech_started"})
        else:
            self._quiet += 1
            if self._in_speech and self._quiet >= 25:        # ≈ 0,5 sn sessizlik (20 ms parçalar)
                self._in_speech = False
                self._loud = 0
                self._q.put_nowait({"type": "speech_stopped"})
                self._q.put_nowait({"type": "user_text", "text": "evet"})
                args = self.script.pop(0) if self.script else dict(self.default)
                self._n_calls += 1
                if args is not None:          # None: model fonksiyon çağırmadı (güvenilirlik testi)
                    self._q.put_nowait({"type": "tool_call", "id": f"call{self._n_calls}", "name": TOOL_NAME, "args": args})
                self._q.put_nowait({"type": "response_done"})

    async def tool_result(self, call_id: str, name: str) -> None:
        self.results.append(call_id)

    async def speak(self, text: str, rule: str | None) -> None:
        self.spoken.append((text, rule))
        self.rule = rule
        seconds = min(4.0, max(0.4, len(text) / 45))
        n = int(seconds * self.out_rate)
        t = np.arange(n) / self.out_rate
        tone = (0.3 * np.sin(2 * math.pi * 440 * t) * 32767).astype(np.int16)
        self._q.put_nowait({"type": "agent_text", "text": text})
        step = self.out_rate // 5
        for i in range(0, n, step):
            self._q.put_nowait({"type": "audio", "pcm": tone[i:i + step].tobytes()})
        self._q.put_nowait({"type": "response_done"})

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def inject_user_text(self, text: str) -> None:
        args = self.script.pop(0) if self.script else dict(self.default)
        self._n_calls += 1
        if args is not None:
            self._q.put_nowait({"type": "tool_call", "id": f"call{self._n_calls}", "name": TOOL_NAME, "args": args})
        self._q.put_nowait({"type": "response_done"})


def make_backend(spec: dict) -> RealtimeBackend:
    kind, model = spec.get("provider"), spec.get("model") or ""
    if kind == "openai_realtime":
        return OpenAIRealtime(model, local_turns=bool(spec.get("local_turns", True)))
    if kind == "gemini_live":
        return GeminiLive(model)
    if kind == "fake_realtime" and os.environ.get("SVA_FAKE_PROVIDERS") == "1":
        return FakeRealtime(model or "fake")
    raise ValueError(f"bilinmeyen realtime sağlayıcı: {kind}")


# ---- oturum -------------------------------------------------------------------------------------------------------
class RealtimeVoiceSession:
    """VoiceSession ile aynı dış arayüz (RtcVoiceConnection bunu kullanır): start, feed, set_phone_filter, close."""

    def __init__(self, sid: str, profile_id: str, backend: RealtimeBackend, out, send_event: Callable[[dict], None],
                 flow, phone_filter: bool = False):
        self.sid, self.profile_id, self.backend, self.out, self.emit, self.flow = sid, profile_id, backend, out, send_event, flow
        self.phone_filter = phone_filter
        self.fixed_audio = None                 # core-019: FixedAudio (sabit yasal metinler için önceden üretilmiş ses)
        self._in_filter = phone.PhoneFilter(SAMPLE_RATE)
        self._out_filter = phone.PhoneFilter(backend.out_rate)
        self.vad = Endpointer()
        self.silence = SilenceGuard()           # core-022
        self.state = "idle"
        self.started_at = datetime.now(timezone.utc)
        self.turns: list[dict] = []
        self.transcript: list[dict] = []
        self.stats = {"frames_in": 0, "seconds_in": 0.0, "utterances": 0, "dropped": 0, "barge_ins": 0,
                      "agent_seconds_out": 0.0, "peak_in_db": -120.0, "holds": 0, "merged": 0, "barge_cut_ms": [],
                      "tool_calls": 0, "invalid_tool_calls": 0, "realtime": backend.kind}
        self._buf = np.zeros(0, np.float32)
        self._send_q: asyncio.Queue[bytes | str | None] = asyncio.Queue()    # bytes: ses; "clear" / "answer": sıralı komut
        self._ring: deque[np.ndarray] = deque(maxlen=20)                      # ajan konuşurken son 400 ms ham ses (söz kesmede sunucuya yetiştirilir)
        self._tasks: list[asyncio.Task] = []
        self._barge = 0
        self._barge_t0 = 0.0
        self._t_end: float | None = None        # yerel VAD'ın konuşma bitişini ilan ettiği an
        self._t_tool: float | None = None
        self._rec: dict[str, Any] = {}
        self._expect = "idle"                   # speak | answer | idle
        self._got_tool = False
        self._drop_audio = False
        self._last_user = ""
        self._first_audio: float | None = None
        self._turn_no = 0
        self._closed = False
        self.flow.coerce = True                 # ses yolunda değer yumuşak dönüştürülür (flow.coerce_obj)
        self._last_spoken = ""
        self.errors: list[str] = []
        out.set_on_drained(self._on_drained)

    # -- durum
    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.emit({"type": "state", "state": state})

    def _say(self, role: str, text: str) -> None:
        item = {"role": role, "text": text, "t": round((datetime.now(timezone.utc) - self.started_at).total_seconds(), 2)}
        self.transcript.append(item)
        self.emit({"type": "transcript", **item})

    def _on_drained(self) -> None:
        if self.state == "speaking":
            self._set_state("listening")
            self._ring.clear()
            if self.backend.local_turns:
                self._send_q.put_nowait("clear")      # yeni dinleme penceresi: tampon yalnız müşteri sesini içersin

    # -- başlangıç
    async def start(self) -> None:
        self._set_state("thinking")
        try:
            await self.backend.connect(INSTRUCTIONS)
        except Exception as exc:  # noqa: BLE001 — anahtar/ağ/model hatası kullanıcıya gösterilir
            self.emit({"type": "error", "message": f"{self.backend.kind} bağlanamadı: {type(exc).__name__}: {exc}"})
            self._set_state("listening")
            return
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._sender()), loop.create_task(self._consume())]
        reply = self.flow.start()
        self._turn_no += 1
        self._rec = {"turn": self._turn_no, "greeting": True, "realtime": True}
        self._t_end = time.perf_counter()
        await self._deliver(reply)

    async def _deliver(self, reply) -> None:
        """FlowDriver cevabını yayınla: olaylar arayüze, metin modele ('AYNEN SÖYLE')."""
        for e in reply.events:
            self.emit(e)
        self._apply_endpointing()
        text = " ".join(reply.utterances)
        if not text:
            self._expect = "idle"
            self._set_state("listening")
            return
        rule = None
        if not self.flow.finished and self.flow.current is not None:
            rule = answer_rule(self.flow.steps[self.flow.current])
        self.backend.set_answer_rule(rule)
        self._say("agent", text)
        self._last_spoken = text
        self._expect = "speak"
        self._first_audio = None
        self._drop_audio = False
        self._set_state("thinking")
        node = next((e["key"] for e in reversed(reply.events) if e.get("type") == "node"), None)
        if node is None and self.flow.current is not None:      # tekrar sorma: aynı adım, yeni 'node' olayı yok
            node = self.flow.steps[self.flow.current].get("key")
        if self.fixed_audio is not None and not reply.finished and self.fixed_audio.applies(node):
            self._tasks.append(asyncio.get_running_loop().create_task(self._play_fixed(text, rule, self._turn_no, node)))
            return
        await self.backend.speak(text, rule)
        self._tasks.append(asyncio.get_running_loop().create_task(self._speak_watchdog(self._turn_no)))

    async def _play_fixed(self, text: str, rule: str | None, turn_no: int, node: str | None) -> None:
        """core-019: sabit yasal metin önceden üretilmiş OpenAI TTS sesiyle çalınır; model konuşmaz, yalnızca dinler."""
        pcm = await self.fixed_audio.get(text)
        if self._closed or turn_no != self._turn_no or self._expect != "speak":
            return
        if pcm is None:                                   # üretilemedi: modele geri dön (verbatim garantisi yok, olay ile bildirilir)
            self.emit({"type": "fixed_audio_fallback", "step": node})
            self.stats["fixed_audio_fallbacks"] = self.stats.get("fixed_audio_fallbacks", 0) + 1
            await self.backend.speak(text, rule)
            self._tasks.append(asyncio.get_running_loop().create_task(self._speak_watchdog(turn_no)))
            return
        step = 960                                        # 20 ms @ 24 kHz, 16 bit
        for i in range(0, len(pcm), step):
            if self._closed or self._drop_audio or turn_no != self._turn_no or self._expect != "speak":
                return                                    # söz kesme: kalan ses atılır
            self._on_audio(pcm[i:i + step], rate=24000)
            await asyncio.sleep(0)
        self.stats["fixed_audio_turns"] = self.stats.get("fixed_audio_turns", 0) + 1
        self._rec = {**(self._rec or {}), "fixed_audio": node, "agent_said": text}
        self._finish_speak()

    async def _speak_watchdog(self, turn_no: int) -> None:
        await asyncio.sleep(SPEAK_TIMEOUT_S)
        if self._expect == "speak" and self._first_audio is None and turn_no == self._turn_no and not self._closed:
            self.emit({"type": "error", "message": f"{self.backend.kind}: {SPEAK_TIMEOUT_S:.0f} sn içinde ses gelmedi"})
            self._expect = "idle"
            self._set_state("listening")

    def _apply_endpointing(self) -> None:
        kind = self.flow.steps[self.flow.current]["kind"] if self.flow.current is not None else None
        self.vad.set_end_ms(END_MS_OPEN if kind == "OpenText" else END_MS_DEFAULT)

    def set_vad(self, cmd: dict) -> None:
        """core-015: yerel eşik anında; sunucu VAD'i (OpenAI) varsa yaklaşık karşılığıyla session.update ile güncellenir."""
        applied = self.vad.configure(threshold_db=cmd.get("db"), barge_frames=cmd.get("barge_frames"),
                                     barge_margin_db=cmd.get("barge_margin_db"), reset_threshold=bool(cmd.get("auto")))
        self.stats["vad"] = applied
        note = self._server_vad_note(applied)
        self.emit({"type": "vad_settings", **applied, "server_side": note})

    def _server_vad_note(self, applied: dict) -> str:
        if self.backend.local_turns:
            return "Tur yönetimi yerel (sunucu VAD'ı kapalı): eşik doğrudan konuşma başlangıç/bitişini ve söz kesmeyi belirler."
        if not hasattr(self.backend, "set_sensitivity"):
            return "Bu profilde sunucu VAD'i ayarlanamıyor: eşik yalnızca yerel söz kesmeyi/uç noktayı etkiler; sunucu kendi VAD'iyle kesebilir."
        db = applied["effective_threshold_db"]
        thr = self.backend.set_sensitivity(db)
        try:
            asyncio.get_running_loop().create_task(self.backend.apply_sensitivity())
        except RuntimeError:   # döngü yok (birim testi): yalnızca değer hesaplandı
            pass
        return f"OpenAI server_vad.threshold={thr} (dBFS'ten yaklaşık eşleme; gerçek mikrofonla doğrulanmadı)"

    def set_phone_filter(self, on: bool) -> None:
        if on != self.phone_filter:
            self.phone_filter = on
            self._in_filter.reset()
            self._out_filter.reset()
        self.emit({"type": "phone_filter", "on": self.phone_filter})

    # -- giriş sesi
    def feed(self, samples: np.ndarray) -> None:
        if self._closed or self.state == "idle":
            return
        samples = samples.astype(np.float32, copy=False)
        if self.phone_filter:
            samples = self._in_filter.process(samples)
        self._buf = np.concatenate([self._buf, samples])
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            self._on_frame(frame)
            # yarı-dupleks: ajan konuşurken/düşünürken sunucuya sessizlik gider. Hoparlör yankısı ve oda gürültüsü sunucu VAD'ını
            # tetikleyip sahte tur/"tam anlayamadım" döngüsü üretiyordu; söz kesmeyi zaten yerel VAD yapar (kesince frames akmaya başlar).
            if self.state == "listening":
                out = frame
            else:
                out = np.zeros_like(frame)
                self._ring.append(frame)
            self._send_q.put_nowait(to_int16(resample(out, SAMPLE_RATE, self.backend.in_rate)).tobytes())

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
            if self._barge >= self.vad.barge_frames and self._first_audio is not None:   # ajan gerçekten konuşuyorsa söz kesme
                self._barge_in()
        else:
            self._barge = 0
        for kind, _ in events:
            if kind == "end" and self.state == "listening":
                self.stats["utterances"] += 1
                self._t_end = time.perf_counter()
                if self.backend.local_turns and self._expect == "idle":
                    self._expect, self._got_tool = "answer", False
                    self._set_state("thinking")
                    self._send_q.put_nowait("answer")     # sırayla: commit, sonra yalnız-fonksiyon cevabı isteği
            elif kind == "drop":
                self.stats["dropped"] += 1
                if self.state == "listening":
                    self.silence.note_drop()
                    if self.backend.local_turns:
                        self._send_q.put_nowait("clear")  # tık/öksürük: sunucu tamponundan at
        if not self.flow.finished and self.flow.current is not None:
            listening = self.state == "listening" and self._expect == "idle"
            if self.silence.tick(listening, self.vad.collecting):
                asyncio.get_running_loop().create_task(self._on_silence())

    async def _on_silence(self) -> None:
        """core-022: müşteriden ses gelmedi; soru tekrarlanır ya da kibarca kapatılır."""
        reply = self.flow.silence()
        self.stats["silences"] = self.stats.get("silences", 0) + 1
        self.emit({"type": "silence", "count": self.flow.silences})
        self._turn_no += 1
        self._rec = {"turn": self._turn_no, "greeting": True, "realtime": True, "silence": True}
        self._t_end = time.perf_counter()
        await self._deliver(reply)

    def _barge_in(self) -> None:
        cut_ms = round((time.perf_counter() - self._barge_t0) * 1000)
        self._barge = 0
        self.out.flush()
        self._drop_audio = True
        self.stats["barge_ins"] += 1
        self.stats["barge_cut_ms"].append(cut_ms)
        self.emit({"type": "barge_in", "cut_ms": cut_ms})
        self._set_state("listening")
        if self.backend.local_turns:
            # yerel tur yönetimi: tamponu temizle, ajan konuşurken sıfırlanan son 400 ms gerçek sesi sunucuya yetiştir
            self._send_q.put_nowait("clear")
            while self._ring:
                self._send_q.put_nowait(to_int16(resample(self._ring.popleft(), SAMPLE_RATE, self.backend.in_rate)).tobytes())
        if self._expect == "speak":          # kesilen konuşma turu biter; müşterinin cevabı sunucu VAD olayıyla alınır
            self._expect = "idle"
            if self._rec:
                self.turns.append(self._rec)
                self.emit({"type": "turn", **self._rec})
                self._rec = {}
        asyncio.get_running_loop().create_task(self.backend.interrupt())

    async def _sender(self) -> None:
        while True:
            pcm = await self._send_q.get()
            if pcm is None:
                return
            try:
                if pcm == "clear":
                    await self.backend.clear_audio()
                elif pcm == "answer":
                    await self.backend.commit_audio()
                    if self.backend.auto_answer:
                        await self.backend.request_answer()
                else:
                    await self.backend.send_audio(pcm)
            except Exception as exc:  # noqa: BLE001
                self.emit({"type": "error", "message": f"{self.backend.kind} ses gönderilemedi: {exc}"})
                return

    # -- sağlayıcı olayları
    async def _consume(self) -> None:
        try:
            async for ev in self.backend.events():
                await self._on_event(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    async def _on_event(self, ev: dict) -> None:
        t = ev["type"]
        if t == "audio":
            self._on_audio(ev["pcm"])
        elif t == "user_text":
            text = ev["text"].strip()
            ok, reason = sttguard.check(text) if text else (True, None)
            if not ok and reason in ("foreign_script", "hallucination_phrase", "repetition_loop"):
                # canlı test (A3): giriş transkriptinde 목동매는 / schwer gibi yabancı yazı; cevap bağlamına ve kayda girmez
                self.stats["stt_rejected"] = self.stats.get("stt_rejected", 0) + 1
                self.emit({"type": "stt_rejected", "reason": reason, "text": text})
                self._last_user = ""
                self._say("user", f"[transkript güvenilmez: {reason}]")
            else:
                self._last_user = text
                if self._last_user:
                    self._say("user", self._last_user)
        elif t == "speech_stopped":
            if self._expect != "speak" and self.state == "listening":   # ajan konuşurken/çalarken gelen ses cevap sayılmaz
                self._expect, self._got_tool = "answer", False
                self._set_state("thinking")
                if self.backend.auto_answer:
                    await self.backend.request_answer()
        elif t == "agent_text":
            # modelin gerçekte söylediği (transkript): sadakat ölçümü. Transkripte biz verdiğimiz metni yazıyoruz; sapma burada görünür.
            self._rec["agent_said"] = (self._rec.get("agent_said", "") + " " + ev["text"]).strip()
        elif t == "tool_call":
            await self._on_tool_call(ev)
        elif t == "response_done":
            await self._on_response_done()
        elif t == "interrupted":
            self.out.flush()
            self._drop_audio = True
        elif t == "error":
            self.errors.append(ev["message"])
            self.emit({"type": "error", "message": ev["message"]})

    def _on_audio(self, pcm_bytes: bytes, rate: int | None = None) -> None:
        if self._drop_audio or not pcm_bytes:
            return
        rate = rate or self.backend.out_rate
        audio = np.frombuffer(pcm_bytes, np.int16).astype(np.float32) / 32768.0
        if self.phone_filter and rate == self.backend.out_rate:
            audio = self._out_filter.process(audio)
        pcm = to_int16(resample(audio, rate, OUT_RATE))
        if self._first_audio is None:
            self._first_audio = time.perf_counter()
            if self._t_end is not None:
                self._rec["first_audio_after_end_s"] = round(self._first_audio - self._t_end, 3)
            if self._t_tool is not None:
                self._rec["speak_s"] = round(self._first_audio - self._t_tool, 3)
            self._set_state("speaking")
        self.stats["agent_seconds_out"] = round(self.stats["agent_seconds_out"] + len(pcm) / OUT_RATE, 2)
        self.out.push(pcm)

    async def _ack(self, ev: dict) -> None:
        """Her fonksiyon çağrısı cevaplanır: Gemini toolResponse gelmeyince tur kapanmaz ve dinlemede kalır."""
        try:
            await self.backend.tool_result(ev.get("id", ""), ev.get("name") or TOOL_NAME)
        except Exception:  # noqa: BLE001
            pass

    async def _on_tool_call(self, ev: dict) -> None:
        if ev.get("name") != TOOL_NAME or self.flow.finished:
            await self._ack(ev)
            return
        if self._expect != "answer":
            if self.backend.auto_answer or self._expect == "speak":
                await self._ack(ev)            # ajan konuşurken ya da sunucu VAD'li hatta beklenmeyen çağrı: yok sayılır
                return
            # Gemini: sunucu konuşma bitişi olayı vermez; çağrının kendisi cevap turudur
            self._expect, self._got_tool = "answer", False
            self._set_state("thinking")
        self._got_tool = True
        self.stats["tool_calls"] += 1
        self._t_tool = time.perf_counter()
        obj = parse_tool_args(ev.get("args"))
        self._turn_no += 1
        self._rec = {"turn": self._turn_no, "realtime": True, "tool_args": ev.get("args")}
        if self._t_end is not None:
            self._rec["answer_s"] = round(self._t_tool - self._t_end, 3)
        try:
            await self.backend.tool_result(ev["id"], TOOL_NAME)
        except Exception:  # noqa: BLE001
            pass
        await self._deliver(self._apply(obj))

    def _apply(self, obj: dict | None):
        reply = self.flow.handle_structured(obj, self._last_user)
        if any(e.get("type") == "understood" and not e.get("valid") for e in reply.events):
            self.stats["invalid_tool_calls"] += 1     # model yanlış tipte/bozuk değer bildirdi
        return reply

    async def _on_response_done(self) -> None:
        if self._expect == "answer" and not self._got_tool:
            # model fonksiyon çağırmadı (güvenilirlik sorunu): cevap anlaşılamadı sayılır, akış tekrar sorar
            self._t_tool = time.perf_counter()
            self._turn_no += 1
            self._rec = {"turn": self._turn_no, "realtime": True, "no_tool_call": True}
            if self._t_end is not None:
                self._rec["answer_s"] = round(self._t_tool - self._t_end, 3)
            self._got_tool = True
            await self._deliver(self._apply(None))
        elif self._expect == "speak":
            if self._first_audio is None:
                # cevap-bildirim yanıtının response.done'ı seslendirme yanıtından önce gelebilir; ses gelmeden bitiş sayılmaz
                # (ses hiç gelmezse _speak_watchdog bırakır)
                return
            self._finish_speak()

    def _finish_speak(self) -> None:
        """Ajan konuşma turu bitti (model yanıtı ya da sabit ses): tur kaydı, verbatim ölçümü, bitiş olayı."""
        self._expect = "idle"
        self.out.mark_end()
        if self._first_audio is None:
            self._set_state("listening")
        if self._rec and self._rec.get("agent_said") and self._last_spoken:
            import difflib
            norm = lambda s: " ".join("".join(ch for ch in s.casefold() if ch.isalnum() or ch.isspace()).split())  # noqa: E731
            self._rec["verbatim"] = round(difflib.SequenceMatcher(None, norm(self._last_spoken), norm(self._rec["agent_said"])).ratio(), 3)
        if self._rec:
            self.turns.append(self._rec)
            self.emit({"type": "turn", **self._rec})
            self._rec = {}
        if self.flow.finished:
            self.emit({"type": "finished", "outcome": self.flow.outcome})

    # -- kapanış
    async def close(self) -> Path | None:
        if self._closed:
            return None
        self._closed = True
        self.out.flush()
        self._send_q.put_nowait(None)
        for task in self._tasks:
            task.cancel()
        try:
            await self.backend.close()
        except Exception:  # noqa: BLE001
            pass
        self._set_state("closed")
        folder = stt_runs.data_dir() / "voice-sessions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.sid}.json"
        path.write_text(json.dumps({
            "id": self.sid, "profile": self.profile_id, "started_at": self.started_at.isoformat(timespec="seconds"),
            "stats": self.stats, "turns": self.turns, "transcript": self.transcript,
            "flow": {"scenario": self.flow.sc["key"], "outcome": self.flow.outcome, "path": self.flow.path,
                     "answers": self.flow.answers},
            "phone_filter": self.phone_filter, "vad": self.vad.settings(), "errors": self.errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
