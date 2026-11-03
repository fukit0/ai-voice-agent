"""API sağlayıcıları (demo / referans profiller): Deepgram, Anthropic, ElevenLabs.

Anahtarlar ortam değişkenlerinden okunur; eksikse çağrı yapılmadan ProviderNotReady döner.
Gerçek müşteri verisi bu sağlayıcılara gönderilmemeli (KVKK; plan: Demo API'leri).
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any, Iterator

import numpy as np

from .audio import encode_wav
from .base import (LLMProvider, LLMResult, ProviderError, STTProvider, STTResult, StreamingSTT, TTSProvider, TTSResult,
                   TTSStream)


# ---- Bağlantı havuzu (A1 gecikme işi, faz 1) -----------------------------------------------------------------------
# Eskiden her çağrı modül düzeyindeki `httpx.post` ile yapılıyordu: her STT/LLM/TTS çağrısı YENİ bir TCP + TLS el sıkışması
# ödüyordu (Mac'te ölçülen A1 ilk ses p50 3,29 sn'nin bir kısmı). Artık her ana bilgisayar (scheme://host:port) için TEK,
# iş parçacığı güvenli bir `httpx.Client` paylaşılır; keep-alive ile bağlantı çağrılar arasında açık kalır.
# - HTTP/2 yalnızca `h2` paketi kuruluysa açılır (yoksa HTTP/1.1; bağımlılık eklenmedi).
# - Zaman aşımları çağrı başına eskisiyle AYNI (_post 60 sn, _get 30 sn): davranış değişmesin.
# - İmport anında ağ çağrısı yok; istemci ilk çağrıda oluşturulur.
# - Sunucunun boşta kapattığı bağlantı yeniden kullanılırsa httpcore "Server disconnected without sending a response"
#   verir: istek sunucuya hiç ulaşmamıştır, bu durumda bir kez yeni bağlantıyla tekrar denenir (eski davranışta zaten her
#   çağrı yeni bağlantıydı; tekrar deneme yalnızca bu bayat bağlantı durumunu eski sonuca eşitler).
KEEPALIVE_EXPIRY_S = 60.0
POOL_LIMITS = {"max_connections": 20, "max_keepalive_connections": 10, "keepalive_expiry": KEEPALIVE_EXPIRY_S}
_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def http2_available() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


def _origin(url: str) -> str:
    import httpx

    u = httpx.URL(url)
    return f"{u.scheme}://{u.host}:{u.port or (443 if u.scheme == 'https' else 80)}"


def client_for(url: str):
    """Bu URL'nin ana bilgisayarı için paylaşılan istemci (yoksa oluşturur)."""
    import httpx

    key = _origin(url)
    with _clients_lock:
        cli = _clients.get(key)
        if cli is None or cli.is_closed:
            cli = httpx.Client(http2=http2_available(), limits=httpx.Limits(**POOL_LIMITS), timeout=60)
            _clients[key] = cli
        return cli


def close_clients() -> None:
    """Tüm paylaşılan istemcileri kapatır (testler ve kapanış için). Sonraki çağrı yenisini açar."""
    with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for cli in clients:
        try:
            cli.close()
        except Exception:  # noqa: BLE001 — kapanış hatası önemsiz
            pass


def _stale(exc: Exception) -> bool:
    """Boşta kapanmış (bayat) keep-alive bağlantısı mı: istek sunucuya ulaşmadı, güvenle bir kez tekrar denenebilir."""
    import httpx

    return isinstance(exc, httpx.RemoteProtocolError) and "without sending a response" in str(exc)


def _request(method: str, url: str, timeout: float, **kwargs):
    cli = client_for(url)
    try:
        return cli.request(method, url, timeout=timeout, **kwargs)
    except Exception as exc:
        if not _stale(exc):
            raise
        return cli.request(method, url, timeout=timeout, **kwargs)


def warm_connection(url: str, timeout: float = 5.0) -> float | None:
    """TCP + TLS el sıkışmasını önceden yapar (ucuz HEAD isteği; HTTP durum kodu önemsiz). Süre (sn) ya da hata olursa None.

    Profil hazırlama / ölçüm betiği çağırabilir; hata fırlatmaz (ısınma yapılamaması çağrıyı bozmamalı)."""
    t0 = time.perf_counter()
    try:
        _request("HEAD", url, timeout)
    except Exception:  # noqa: BLE001
        return None
    return time.perf_counter() - t0


def _post(url: str, **kwargs):
    try:
        res = _request("POST", url, kwargs.pop("timeout", 60), **kwargs)
    except Exception as exc:
        raise ProviderError(f"{url} çağrısı başarısız: {exc}") from exc
    if res.status_code >= 400:
        raise ProviderError(f"{url} HTTP {res.status_code}: {res.text[:200]}")
    return res


def _post_stream(url: str, **kwargs) -> tuple[float, float, bytes]:
    """Akışlı POST: (ilk ses baytına kadar sn, toplam sn, gövde). Canlı hatta önemli olan ilk ses süresini ölçer."""
    t0 = time.perf_counter()
    first, chunks = None, []
    for chunk in _stream_bytes(url, kwargs.pop("timeout", 60), **kwargs):
        if chunk and first is None:
            first = time.perf_counter() - t0
        chunks.append(chunk)
    total = time.perf_counter() - t0
    return (first if first is not None else total), total, b"".join(chunks)


def _stream_bytes(url: str, timeout: float = 60, **kwargs) -> Iterator[bytes]:
    """Akışlı POST gövdesini parça parça verir. Hatalar `_post_stream` ile aynı ProviderError mesajlarıyla döner.
    Üreteç erken kapatılırsa (GeneratorExit: söz kesme) HTTP yanıtı hemen kapanır, bağlantı havuza bırakılmaz ya da bırakılır
    (httpx kararı); okunmamış gövde beklenmez."""
    cli = client_for(url)
    for attempt in (0, 1):
        try:
            with cli.stream("POST", url, timeout=timeout, **kwargs) as res:
                if res.status_code >= 400:
                    res.read()
                    raise ProviderError(f"{url} HTTP {res.status_code}: {res.text[:200]}")
                for chunk in res.iter_bytes():
                    yield chunk
            return
        except ProviderError:
            raise
        except GeneratorExit:
            raise
        except Exception as exc:
            if attempt == 0 and _stale(exc):
                continue        # bayat bağlantı: hiç bayt gelmeden düştü, bir kez yeni bağlantıyla dene
            raise ProviderError(f"{url} çağrısı başarısız: {exc}") from exc


def _get(url: str, **kwargs):
    try:
        res = _request("GET", url, kwargs.pop("timeout", 30), **kwargs)
    except Exception as exc:
        raise ProviderError(f"{url} çağrısı başarısız: {exc}") from exc
    if res.status_code >= 400:
        raise ProviderError(f"{url} HTTP {res.status_code}: {res.text[:200]}")
    return res


class _Prewarm:
    """Uzak sağlayıcılar için bağlantı ısıtma (TCP + TLS). Model/çıktı yok; yalnızca havuzdaki bağlantıyı açar."""
    WARM_URL: str = ""

    def prewarm(self) -> float | None:
        return warm_connection(self.WARM_URL) if self.WARM_URL else None


class DeepgramSTT(_Prewarm, STTProvider):
    kind = "deepgram"
    required_env = ("DEEPGRAM_API_KEY",)
    WARM_URL = "https://api.deepgram.com/"

    def transcribe(self, audio, sample_rate, language="tr"):
        t0 = time.perf_counter()
        res = _post(
            "https://api.deepgram.com/v1/listen",
            params={"model": self.model or "nova-3", "language": language, "smart_format": "true"},
            headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"},
            content=encode_wav(audio, sample_rate),
        )
        alt = res.json()["results"]["channels"][0]["alternatives"][0]
        return STTResult(text=alt.get("transcript", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model, extra={"confidence": alt.get("confidence")})


    # ---- Akışlı tanıma (faz 3, isteğe bağlı: profilde stt.streaming: true) ----------------------------------------------
    WS_URL = "wss://api.deepgram.com/v1/listen"

    @property
    def streaming(self) -> bool:
        """Profil seçeneği `streaming: true` ise VoiceSession konuşma sürerken sesi canlı bağlantıya akıtır (A1S). A1'de kapalı."""
        return bool(self.options.get("streaming"))

    def open_stream(self, sample_rate: int = 16000, language: str = "tr") -> "DeepgramLiveStream":
        """Tek konuşma için canlı bağlantı nesnesi (henüz açılmamış; `open()` arka planda açar).
        Sorgu: toplu çağrıyla aynı model/dil/smart_format + linear16 PCM; Deepgram'ın kendi bitiş tespiti KAPALI
        (endpointing=false): konuşma bitişine yerel VAD karar verir, sonra Finalize gönderilir. Ara sonuç istenmez
        (interim_results=false): yalnız kesinleşmiş parçalar birleştirilir."""
        params = {"model": self.model or "nova-3", "language": language, "encoding": "linear16", "sample_rate": str(sample_rate),
                  "channels": "1", "punctuate": "true", "smart_format": "true", "interim_results": "false", "endpointing": "false"}
        from urllib.parse import urlencode
        o = self.options
        return DeepgramLiveStream(f"{self.WS_URL}?{urlencode(params)}",
                                  {"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}"},
                                  model=self.model, sample_rate=sample_rate,
                                  open_timeout=float(o.get("stream_open_timeout_s", 3.0)),
                                  finish_timeout=float(o.get("stream_finish_timeout_s", 1.5)),
                                  keepalive_s=float(o.get("stream_keepalive_s", 4.0)))


_FINISH, _ABORT = object(), object()


class DeepgramLiveStream(StreamingSTT):
    """Deepgram canlı WebSocket oturumu (tek konuşma). Ayrıntı: StreamingSTT sözleşmesi (base.py).

    İş parçacıkları: gönderici (bağlanır, sıradaki sesi yollar, boşta KeepAlive atar) + alıcı (Results/Metadata okur).
    Bitiş: Finalize + CloseStream; `from_finalize` sonucu, Metadata ya da sunucunun kapatması gelince transkript tamamdır.
    Her hata `error`a yazılır ve `finish()` ProviderError fırlatır: VoiceSession bu durumda konuşmayı toplu çağrıyla yeniden
    çözer (yedek yol)."""

    MAX_IDLE_S = 20.0      # hiç ses/komut gelmezse bağlantı kendini kapatır (sızıntı koruması: oturum çökerse sonsuz KeepAlive yok)

    def __init__(self, url: str, headers: dict, *, model: str = "", sample_rate: int = 16000, open_timeout: float = 3.0,
                 finish_timeout: float = 1.5, keepalive_s: float = 4.0):
        self.url, self.headers, self.model, self.sample_rate = url, headers, model, sample_rate
        self.open_timeout, self.finish_timeout, self.keepalive_s = open_timeout, finish_timeout, keepalive_s
        self.q: queue.Queue = queue.Queue()
        self.done = threading.Event()
        self.error: str | None = None
        self.segments: list[tuple[str, float | None, float | None]] = []
        self.keepalives = 0
        self.sent_bytes = 0
        self.opened_at: float | None = None
        self.connected_at: float | None = None
        self.closed_at: float | None = None
        self._finish_sent = False
        self._ended = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- sözleşme --
    def open(self) -> None:
        self.opened_at = time.perf_counter()
        self._thread = threading.Thread(target=self._run, name="deepgram-live", daemon=True)
        self._thread.start()

    def send(self, pcm16: bytes) -> None:
        if not self._ended:
            self.q.put(bytes(pcm16))

    def abort(self) -> None:
        self._ended = True
        self.q.put(_ABORT)

    def finish(self) -> STTResult:
        t0 = time.perf_counter()
        self._ended = True
        self.q.put(_FINISH)
        if not self.done.wait(self.finish_timeout):
            self.q.put(_ABORT)
            raise ProviderError(f"Deepgram akış: son transkript {self.finish_timeout:.1f} sn içinde gelmedi")
        if self.error:
            raise ProviderError(f"Deepgram akış: {self.error}")
        with self._lock:
            segs = list(self.segments)
        texts = [t for t, _, _ in segs if t]
        weights = [(c, d if isinstance(d, (int, float)) and d > 0 else max(1, len(t.split())))
                   for t, c, d in segs if t and isinstance(c, (int, float))]
        conf = sum(c * w for c, w in weights) / sum(w for _, w in weights) if weights else None
        return STTResult(text=" ".join(texts).strip(), seconds=time.perf_counter() - t0, provider="deepgram", model=self.model,
                         extra={"confidence": conf, "stream": True, "segments": len(texts), "keepalives": self.keepalives})

    def billed_seconds(self) -> float:
        if self.connected_at is None:
            return 0.0
        return max(0.0, (self.closed_at or time.perf_counter()) - self.connected_at)

    @property
    def sent_seconds(self) -> float:
        return self.sent_bytes / (2 * self.sample_rate)

    # -- iç --
    def _fail(self, msg: str) -> None:
        with self._lock:
            if self.error is None and not (self._finish_sent and self.done.is_set()):
                self.error = msg
        self.done.set()

    def _run(self) -> None:
        from websockets.sync.client import connect

        try:
            conn = connect(self.url, additional_headers=self.headers, open_timeout=self.open_timeout, close_timeout=1.0,
                           compression=None, max_size=2 ** 22)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"bağlantı açılamadı: {type(exc).__name__}: {exc}")
            return
        try:
            with conn as ws:     # websockets >= 17.1 bağlamsız kullanımı kullanımdan kaldırdı; çıkışta bağlantı kapanır
                self._pump(ws)
        except Exception:  # noqa: BLE001 — kapanış hatası önemsiz (sonuç/hata zaten kaydedildi)
            pass
        finally:
            self.closed_at = time.perf_counter()

    def _pump(self, ws) -> None:
        self.connected_at = time.perf_counter()
        rx = threading.Thread(target=self._recv, args=(ws,), name="deepgram-live-rx", daemon=True)
        rx.start()
        idle = 0.0
        try:
            while True:
                try:
                    item = self.q.get(timeout=self.keepalive_s)
                except queue.Empty:
                    idle += self.keepalive_s
                    if idle >= self.MAX_IDLE_S:
                        self._fail("bağlantı boşta kaldı (ses gelmedi)")
                        break
                    ws.send(json.dumps({"type": "KeepAlive"}))      # Deepgram ~10 sn sessiz bağlantıyı kapatır
                    self.keepalives += 1
                    continue
                idle = 0.0
                if item is _ABORT:
                    break
                if item is _FINISH:
                    self._finish_sent = True
                    ws.send(json.dumps({"type": "Finalize"}))
                    ws.send(json.dumps({"type": "CloseStream"}))
                    self.done.wait(self.finish_timeout)
                    break
                ws.send(item)
                self.sent_bytes += len(item)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"gönderim hatası: {type(exc).__name__}: {exc}")

    def _recv(self, ws) -> None:
        try:
            for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                kind = data.get("type")
                if kind == "Results":
                    if data.get("is_final"):
                        alt = (((data.get("channel") or {}).get("alternatives")) or [{}])[0]
                        with self._lock:
                            self.segments.append(((alt.get("transcript") or "").strip(), alt.get("confidence"), data.get("duration")))
                    if data.get("from_finalize") and self._finish_sent:
                        self.done.set()
                elif kind == "Metadata":
                    if self._finish_sent:
                        self.done.set()
                elif kind == "Error" or "err_code" in data:
                    self._fail(f"sunucu hatası: {str(data.get('description') or data.get('err_msg') or data)[:200]}")
        except Exception as exc:  # noqa: BLE001 — ConnectionClosedError (1000/1001 dışı kapanış kodu) dahil
            # Finalize gönderilmiş olsa bile anormal kapanış hatadır (son sonuç gelmeden düştü); son sonuç zaten geldiyse
            # _fail bunu yok sayar.
            self._fail(f"bağlantı konuşma ortasında kapandı: {type(exc).__name__}: {exc}"[:200])
        finally:
            if self._finish_sent:
                self.done.set()           # CloseStream sonrası kapanış: toplanan parçalar tamam
            else:
                self._fail("bağlantı konuşma ortasında kapandı")


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def anthropic_headers() -> dict:
    """Anthropic Messages API başlıkları (AnthropicLLM ve serbest cevabın Haiku istemcisi ortak kullanır; voice/free_reply.py).
    Anahtar ortamdan (ANTHROPIC_API_KEY, .env main.py'de yüklenir); yoksa KeyError: çağıran önce varlığını denetler."""
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # çalışma alanına bağlı olmayan anahtarlar bu başlığı ister
        headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    return headers


class AnthropicLLM(_Prewarm, LLMProvider):
    kind = "anthropic"
    required_env = ("ANTHROPIC_API_KEY",)
    WARM_URL = "https://api.anthropic.com/"

    def prewarm(self) -> float | None:
        """TLS + tek kısa gerçek istek (ölçüm: soğuk ilk LLM çağrısı 1,75-2,6 sn, ısınmış ~1,0 sn). Hata -> None, arama engellenmez."""
        t0 = time.perf_counter()
        tls = warm_connection(self.WARM_URL)      # önce yalnız bağlantı; istek başarısız olsa bile bu ısıtma geçerlidir
        try:
            self.complete([{"role": "system", "content": "Sen bir bağlantı denemesisin."},
                           {"role": "user", "content": "Sadece 'tamam' yaz."}], 16, 0.0)
        except Exception:  # noqa: BLE001
            return tls
        return time.perf_counter() - t0

    def complete(self, messages, max_tokens=256, temperature=0.3):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": chat}
        if not getattr(self, "_no_temperature", False):
            payload["temperature"] = temperature  # yeni modeller reddeder ("temperature is deprecated"): aşağıda yeniden denenir
        if system:
            # Opt-in (profilde llm.prompt_cache: true): sistem istemi önbellek bloğu olur. Haiku 5.5 için asgari 512 token; altındaki
            # istemler hatasız ama önbelleksiz işlenir. Kazanç ölçülmeden açılmaz (scripts/latency_probe.py --llm-cache).
            if (getattr(self, "options", None) or {}).get("prompt_cache") and not getattr(self, "_no_cache_control", False):
                payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            else:
                payload["system"] = system
        if not getattr(self, "_no_thinking_param", False):
            # Canlı ölçüm (core-012, 38/342 + 38/237 boş çıktı): Haiku 5.5 varsayılan olarak düşünüyor ve kısa max_tokens'ı (120) düşünmeye harcayıp
            # metin üretmeden bitiyor (stop_reason=max_tokens, yalnız 'thinking' bloğu). Kısa yapılandırılmış cevapta düşünme kapatılır.
            payload["thinking"] = {"type": "disabled"}
        t0 = time.perf_counter()
        headers = anthropic_headers()
        try:
            while True:
                try:
                    res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
                    break
                except ProviderError as exc:
                    msg = str(exc).lower()
                    if "temperature" in msg and "temperature" in payload:
                        payload.pop("temperature")  # bu model sıcaklık parametresini kabul etmiyor: bir daha gönderme
                        self._no_temperature = True
                    elif "cache_control" in msg and isinstance(payload.get("system"), list):
                        payload["system"] = system   # önbellek bloğu reddedildi: düz metne dön, bir daha deneme
                        self._no_cache_control = True
                    elif "thinking" in msg and "thinking" in payload:
                        payload.pop("thinking")     # bu model 'disabled' kabul etmiyor: bir daha gönderme
                        self._no_thinking_param = True
                    else:
                        raise
        except ProviderError as exc:
            if "workspace" in str(exc).lower() and not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
                raise ProviderError(
                    "Anthropic anahtarı bir çalışma alanına (workspace) bağlı değil. .env dosyasına "
                    "ANTHROPIC_WORKSPACE_ID=<çalışma alanı kimliği> ekleyip backend'i yeniden başlatın "
                    "(Console > Settings > Workspaces) ya da çalışma alanına bağlı bir anahtar kullanın.") from exc
            raise
        body = res.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        if not text.strip() and body.get("stop_reason") == "max_tokens" and max_tokens < 2048:
            # düşünme kapatılamadıysa: bütçeyi büyütüp bir kez daha dene (boş çıktı 'anlaşılmadı' sayılıp müşteriye yanlış tekrar sordurur)
            payload["max_tokens"] = max(max_tokens * 8, 1024)
            res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            body = res.json()
            text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        extra = {"stop_reason": body.get("stop_reason"), "blocks": [b.get("type") for b in body.get("content", [])]}
        u = body.get("usage", {})
        if u.get("cache_creation_input_tokens") is not None or u.get("cache_read_input_tokens") is not None:
            extra["cache_creation_input_tokens"] = u.get("cache_creation_input_tokens", 0)
            extra["cache_read_input_tokens"] = u.get("cache_read_input_tokens", 0)
        return LLMResult(text=text.strip(), seconds=time.perf_counter() - t0, provider=self.kind, model=self.model,
                         output_tokens=body.get("usage", {}).get("output_tokens"),
                         # önbellek açıkken usage.input_tokens yalnız ÖNBELLEKSİZ kısımdır; maliyet için hepsi tam fiyattan sayılır (üst sınır)
                         input_tokens=(None if u.get("input_tokens") is None else
                                       u["input_tokens"] + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)),
                         extra=extra)


class ElevenLabsTTS(_Prewarm, TTSProvider):
    kind = "elevenlabs"
    WARM_URL = "https://api.elevenlabs.io/"
    # Ses kimliği artık zorunlu ortam değişkeni değil: Persona > Ses stüdyosu'ndan atanan ses de yeterli (readiness_issues denetler).
    required_env = ("ELEVENLABS_API_KEY",)
    SAMPLE_RATE = 24000

    def readiness_issues(self) -> list[str]:
        from .. import tone_voice

        miss = tone_voice.missing_voice_tones()
        if not miss:
            return []
        return [f"ses atanmamış tonlar: {', '.join(miss)}. Persona > Ses stüdyosu'ndan 'Genel ses' ya da bu tonlara ses atayın "
                "(veya ELEVENLABS_VOICE_ID tanımlayın)"]

    def request(self, text, language="tr", speed=1.0, tone=None, voice=None):
        """İstek gövdesi ve ses kimliği (synthesize ve TTS laboratuvarı ortak kullanır). `voice` verilirse en yüksek öncelik."""
        from .. import tone_voice

        model = self.model or "eleven_flash_v2_5"
        body = {"text": text, "model_id": model}
        if "multilingual_v2" not in model:   # language_code multilingual_v2'de desteklenmiyor
            body["language_code"] = language
        tp = tone_voice.params(self.kind, model, tone)   # ton -> voice_settings (+ v3/v4'te ses etiketi); ton yoksa {}
        vs = {k: tp[k] for k in ("stability", "similarity_boost", "style", "use_speaker_boost") if k in tp}
        eff = tp.get("speed", 1.0) * speed   # ton hızı persona hızıyla çarpılır
        if eff != 1.0:   # ElevenLabs voice_settings.speed kabul aralığı 0.7-1.2
            vs["speed"] = round(min(1.2, max(0.7, eff)), 3)
        if vs:
            body["voice_settings"] = vs
        if tp.get("tag") and tone_voice.uses_tags(model):
            body["text"] = f"{tp['tag']} {text}"
        if self.options.get("seed") is not None:   # A/B karşılaştırmada tekrarlanabilirlik (best-effort)
            body["seed"] = int(self.options["seed"])
        # Ton başına ayrı ses (Voice Library/Voice Design): ELEVENLABS_VOICE_ID_ENERJIK vb. tanımlıysa o kullanılır.
        # voice_settings'ten çok daha belirgin fark verir; tanımlı değilse tek ses + ayar kullanılır.
        # Öncelik: açık `voice` > ton ortam değişkeni > ekrandan o tona atanan ses > ekrandan Genel ses > ELEVENLABS_VOICE_ID
        voice = voice or tone_voice.resolve_voice(tone)
        if not voice:
            raise ProviderError("ElevenLabs sesi yok: Persona > Ses stüdyosu'ndan 'Genel ses' ya da bu tona ses atayın "
                                "(veya ELEVENLABS_VOICE_ID tanımlayın).")
        return voice, body

    def synthesize(self, text, language="tr", speed=1.0, tone=None, voice=None):
        t0 = time.perf_counter()
        voice, body = self.request(text, language, speed, tone, voice=voice)   # voice: eval-001 test müşterisi sesleri
        res = _post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json=body,
        )
        audio = np.frombuffer(res.content, dtype="<i2").astype(np.float32) / 32768.0
        return TTSResult(audio=audio, sample_rate=self.SAMPLE_RATE, seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)

    # ---- Akışlı üretim (faz 2, isteğe bağlı: profilde tts.streaming: true) ----------------------------------------------
    @property
    def streaming(self) -> bool:
        """Profil seçeneği `streaming: true` ise VoiceSession cümle sesini parça parça çalar (A1S). A1'de kapalı."""
        return bool(self.options.get("streaming"))

    def synthesize_stream(self, text, language="tr", speed=1.0, tone=None, voice=None) -> TTSStream:
        """`POST /v1/text-to-speech/{voice}/stream` (pcm_24000): gelen baytları float32 parçalar olarak verir.
        İstek gövdesi `synthesize` ile aynıdır (`request`). Ses kimliği yoksa ProviderError hemen fırlar."""
        voice, body = self.request(text, language, speed, tone, voice=voice)
        raw = _stream_bytes(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream",
            params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json=body,
        )
        return TTSStream(pcm16_chunks(raw), self.SAMPLE_RATE)


def pcm16_chunks(raw: Iterator[bytes]) -> Iterator[np.ndarray]:
    """Little-endian int16 bayt akışı -> float32 parçalar. HTTP parça sınırı tek bayta düşebilir (örnek ortasından bölünür):
    artan tek bayt bir sonraki parçanın başına eklenir; akış sonunda tek bayt kalırsa (bozuk gövde) atılır."""
    carry = b""
    try:
        for chunk in raw:
            if not chunk:
                continue
            if carry:
                chunk, carry = carry + chunk, b""
            n = len(chunk) & ~1
            if n < len(chunk):
                carry = chunk[n:]
            if n:
                yield np.frombuffer(chunk[:n], dtype="<i2").astype(np.float32) / 32768.0
    finally:
        close = getattr(raw, "close", None)
        if close is not None:
            close()
