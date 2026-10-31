"""A1 gecikme işi, faz 2: ElevenLabs akışlı TTS (isteğe bağlı, profilde tts.streaming: true).

- Sağlayıcı: /stream uç noktası, tek bayta düşen int16 sınırı, istek gövdesi `synthesize` ile aynı.
- Ses işleme: parça parça yeniden örnekleme = tüm dizi resample_poly; akış telefon filtresi parça sınırında süreksizlik yok.
- Oturum: parçalar geldikçe itilir, tts_first_s ilk parçaya kadar; ilk parçadan önce hata -> akışsız yedek; sonra hata ->
  cümle temiz biter; söz kesmede akış durur; streaming kapalıyken eski yol.
Gerçek ağ yok: yerel http.server ve sahte sağlayıcılar.
"""
import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest
from scipy import signal

from backend.app.providers import registry, remote
from backend.app.providers.audio import resample
from backend.app.providers.base import ProviderError, TTSProvider, TTSResult, TTSStream
from backend.app.voice import phone
from backend.app.voice.session import OUT_RATE, VoiceSession, to_int16
from backend.app.voice.streamaudio import ChunkPipeline, StreamPhoneFilter, StreamResampler

RNG = np.random.default_rng(7)


def tone(seconds=0.5, rate=24000, f=300.0, amp=0.3):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def random_split(x, lo=1, hi=900):
    out, i = [], 0
    while i < len(x):
        k = int(RNG.integers(lo, hi))
        out.append(x[i:i + k])
        i += k
    return out


# ---- bayt -> örnek ---------------------------------------------------------------------------------------------------
def test_pcm16_chunks_handles_odd_byte_boundaries():
    pcm = (RNG.integers(-32768, 32767, 4001)).astype("<i2")
    raw = pcm.tobytes()
    cuts = sorted(set(int(c) for c in RNG.integers(1, len(raw), 60)))   # çoğu tek sayı: örnek ortasından bölünür
    parts = [raw[a:b] for a, b in zip([0] + cuts, cuts + [len(raw)])] + [b""]
    got = np.concatenate(list(remote.pcm16_chunks(iter(parts))))
    assert np.array_equal(got, pcm.astype(np.float32) / 32768.0)


def test_pcm16_chunks_drops_a_trailing_odd_byte_and_closes_source():
    closed = []

    def src():
        try:
            yield b"\x01\x00\x02"
        finally:
            closed.append(True)
    got = np.concatenate(list(remote.pcm16_chunks(src())))
    assert got.tolist() == [1 / 32768.0] and closed == [True]


# ---- ElevenLabs akış uç noktası (yerel sunucu) -----------------------------------------------------------------------
class _EL(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        import json
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append({"path": self.path, "body": body, "key": self.headers.get("xi-api-key")})
        if self.server.status != 200:
            msg = b"kota doldu"
            self.send_response(self.server.status)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        raw = self.server.pcm.tobytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(0, len(raw), 777):          # tek uzunluklu HTTP parçaları
            part = raw[i:i + 777]
            self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


@pytest.fixture()
def eleven(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _EL)
    srv.daemon_threads = True
    srv.seen, srv.status = [], 200
    srv.pcm = (tone(0.3) * 32767).astype("<i2")
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    real = remote._stream_bytes
    monkeypatch.setattr(remote, "_stream_bytes", lambda url, *a, **kw: real(url.replace("https://api.elevenlabs.io", base), *a, **kw))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k-test")
    remote.close_clients()
    yield srv
    remote.close_clients()
    srv.shutdown()
    srv.server_close()


def test_synthesize_stream_uses_stream_endpoint_and_same_body(eleven):
    tts = remote.ElevenLabsTTS("eleven_flash_v2_5", streaming=True)
    stream = tts.synthesize_stream("Merhaba.", "tr", voice="VoiceAbcdef1234")
    assert isinstance(stream, TTSStream) and stream.sample_rate == 24000
    audio = np.concatenate(list(stream))
    assert np.array_equal(audio, eleven.pcm.astype(np.float32) / 32768.0)
    seen = eleven.seen[0]
    assert seen["path"] == "/v1/text-to-speech/VoiceAbcdef1234/stream?output_format=pcm_24000"
    assert seen["key"] == "k-test"
    _, body = tts.request("Merhaba.", "tr", voice="VoiceAbcdef1234")
    assert seen["body"] == body                         # gövde akışsız synthesize ile aynı


def test_synthesize_stream_http_error_is_provider_error(eleven):
    eleven.status = 429
    stream = remote.ElevenLabsTTS("eleven_flash_v2_5").synthesize_stream("x", voice="VoiceAbcdef1234")
    with pytest.raises(ProviderError) as e:
        list(stream)
    assert "HTTP 429: kota doldu" in str(e.value)


def test_streaming_option_reaches_provider_and_is_off_by_default(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    a = registry.get_provider({"provider": "elevenlabs", "model": "eleven_flash_v2_5"}, "tts", "A1")
    b = registry.get_provider({"provider": "elevenlabs", "model": "eleven_flash_v2_5", "streaming": True}, "tts", "A1S")
    assert a is not b and a.streaming is False and b.streaming is True
    assert b.options == {"streaming": True}


# ---- durumlu ses işleme ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("src,dst", [(24000, 48000), (16000, 48000), (22050, 48000), (48000, 16000), (24000, 24000)])
def test_stream_resampler_equals_whole_array_resample_poly(src, dst):
    for n in (1, 9, 333, 12001):
        x = (RNG.standard_normal(n) * 0.3).astype(np.float32)
        rs = StreamResampler(src, dst)
        y = np.concatenate([rs.process(c) for c in random_split(x)] + [rs.flush()])
        ref = resample(x, src, dst)
        assert len(y) == len(ref)
        assert np.max(np.abs(y - ref)) < 1e-5


def test_stream_phone_filter_chunks_equal_whole_and_magnitude_matches_filtfilt():
    x = (RNG.standard_normal(24000) * 0.2).astype(np.float32)
    f = StreamPhoneFilter(24000)
    chunked = np.concatenate([f.process(c) for c in random_split(x)])
    whole = StreamPhoneFilter(24000).process(x)
    assert np.max(np.abs(chunked - whole)) < 1e-6          # parça sınırında süreksizlik yok
    sos = phone._sos(24000)
    w, h_ff = signal.sosfreqz(sos, worN=2048, fs=24000)
    _, h_st = signal.sosfreqz(StreamPhoneFilter(24000).sos, worN=2048, fs=24000)
    assert np.allclose(np.abs(h_st), np.abs(h_ff) ** 2, atol=1e-9)   # genlik = sosfiltfilt (|H|^2)
    band = tone(1.0, f=1000.0)
    ratio = np.sqrt(np.mean(StreamPhoneFilter(24000).process(band)[4000:] ** 2)) / np.sqrt(np.mean(phone.apply(band, 24000)[4000:] ** 2))
    assert 0.97 < ratio < 1.03


def test_chunk_pipeline_chunked_equals_single_feed_and_coalesces_small_chunks():
    x = tone(0.8, f=440.0)
    for pf in (False, True):
        p1 = ChunkPipeline(24000, OUT_RATE, phone_filter=pf)
        a = np.concatenate([p1.feed(c) for c in random_split(x, 1, 300)] + [p1.finish()])
        p2 = ChunkPipeline(24000, OUT_RATE, phone_filter=pf)
        b = np.concatenate([p2.feed(x), p2.finish()])
        assert len(a) == len(b) == 2 * len(x)
        assert np.max(np.abs(a.astype(int) - b.astype(int))) <= 1
    p = ChunkPipeline(24000, OUT_RATE)
    assert len(p.feed(np.zeros(100, np.float32))) == 0        # 40 ms'den küçük: biriktirilir
    assert len(p.feed(np.zeros(900, np.float32))) > 0


def test_chunk_pipeline_without_phone_filter_matches_old_path():
    x = tone(0.6, f=520.0)
    p = ChunkPipeline(24000, OUT_RATE)
    got = np.concatenate([p.feed(c) for c in random_split(x)] + [p.finish()])
    old = to_int16(resample(x, 24000, OUT_RATE))
    assert len(got) == len(old) and np.max(np.abs(got.astype(int) - old.astype(int))) <= 1


# ---- oturum entegrasyonu ---------------------------------------------------------------------------------------------
class Out:
    def __init__(self):
        self.pushed, self.flushed, self.ended, self.cb = [], 0, 0, None
        self.log = []

    def set_on_drained(self, cb):
        self.cb = cb

    def push(self, pcm):
        self.pushed.append(pcm)
        self.log.append(("push", len(pcm)))

    def flush(self):
        self.flushed += 1
        self.pushed.clear()
        self.log.append(("flush", 0))

    def mark_end(self):
        self.ended += 1


class StreamTTS(TTSProvider):
    """Sahte akışlı TTS: her cümle 0,5 sn sinüs; parçalar `chunk` örnek. Davranış bayraklarıyla hata/gecikme üretir."""
    kind = "stream_tts"

    def __init__(self, model="m", chunk=1201, fail_before=False, fail_after=0, first_delay=0.0, gate=None, empty=False, **opts):
        super().__init__(model, **opts)
        self.chunk, self.fail_before, self.fail_after = chunk, fail_before, fail_after
        self.first_delay, self.gate, self.empty = first_delay, gate, empty
        self.synth_calls, self.stream_calls, self.closed, self.yielded = [], [], 0, 0

    def audio_for(self, text):
        return tone(0.5, f=300.0 + 10 * (len(text) % 20))

    def synthesize(self, text, language="tr", speed=1.0, tone=None):
        self.synth_calls.append(text)
        return TTSResult(self.audio_for(text), 24000, 0.01, self.kind, self.model)

    def synthesize_stream(self, text, language="tr", speed=1.0, tone=None):
        self.stream_calls.append(text)
        audio = self.audio_for(text)
        owner = self

        def gen():
            try:
                if owner.fail_before:
                    raise ProviderError("akış açılamadı")
                if owner.empty:
                    return
                if owner.first_delay:
                    time.sleep(owner.first_delay)
                for n, i in enumerate(range(0, len(audio), owner.chunk)):
                    if owner.fail_after and n == owner.fail_after:
                        raise ProviderError("akış koptu")
                    if owner.gate is not None and n >= 1:
                        owner.gate.wait(2)
                    owner.yielded += 1
                    yield audio[i:i + owner.chunk]
            finally:
                owner.closed += 1
        return TTSStream(gen(), 24000)


def session(tmp_path, monkeypatch, tts, phone_filter=False):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    from backend.app.providers.fake import FakeLLM, FakeSTT
    out, events = Out(), []
    s = VoiceSession("st1", "A1S", FakeSTT("m"), FakeLLM("m"), tts, out, events.append, phone_filter=phone_filter)
    s.state = "listening"
    return s, out, events


def expected_pcm(tts, text, phone_filter=False):
    from backend.app import trnorm
    a = tts.audio_for(trnorm.normalize(text))
    if phone_filter:
        p = ChunkPipeline(24000, OUT_RATE, phone_filter=True)
        return np.concatenate([p.feed(a), p.finish()])
    return to_int16(resample(a, 24000, OUT_RATE))


def speak(s, text, turn=None):
    async def go():
        t = turn if turn is not None else s._next_turn()
        await s._speak_turn(text, t, time.perf_counter(), rec={"turn": t})
    asyncio.run(go())


def test_streaming_session_pushes_chunks_and_matches_non_streaming_audio(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True)
    s, out, events = session(tmp_path, monkeypatch, tts)
    speak(s, "Merhaba nasılsınız.")
    got = np.concatenate(out.pushed)
    want = expected_pcm(tts, "Merhaba nasılsınız.")
    assert len(out.pushed) > 3                                   # parça parça itildi
    assert len(got) == len(want) and np.max(np.abs(got.astype(int) - want.astype(int))) <= 1
    assert tts.synth_calls == [] and len(tts.stream_calls) == 1 and tts.closed == 1
    turn = next(e for e in events if e["type"] == "turn")
    assert "tts_first_s" in turn and "first_audio_after_end_s" in turn and turn["tts_total_s"] >= turn["tts_first_s"]
    assert s.usage.tts["calls"] == 1 and s.usage.tts["chars"] == len("Merhaba nasılsınız.")
    assert s.usage.tts["audio_s"] == pytest.approx(0.5)
    assert s.stats["agent_seconds_out"] == pytest.approx(round(len(got) / OUT_RATE, 2))
    assert out.ended == 1 and "tts_stream_fallbacks" not in s.stats


def test_streaming_with_phone_filter_has_no_chunk_discontinuity(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True, chunk=333)
    s, out, _ = session(tmp_path, monkeypatch, tts, phone_filter=True)
    speak(s, "Telefon hattı.")
    got = np.concatenate(out.pushed)
    want = expected_pcm(tts, "Telefon hattı.", phone_filter=True)
    assert len(got) == len(want) and np.max(np.abs(got.astype(int) - want.astype(int))) <= 1


def test_tts_first_s_is_time_to_first_chunk(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True, first_delay=0.15)
    s, _, events = session(tmp_path, monkeypatch, tts)
    speak(s, "Bir.")
    turn = next(e for e in events if e["type"] == "turn")
    assert 0.15 <= turn["tts_first_s"] < 0.6


def test_error_before_first_chunk_falls_back_to_synthesize(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True, fail_before=True)
    s, out, events = session(tmp_path, monkeypatch, tts)
    speak(s, "Yedek yol.")
    assert tts.synth_calls == ["Yedek yol."] and s.stats["tts_stream_fallbacks"] == 1
    got = np.concatenate(out.pushed)
    assert np.array_equal(got, expected_pcm(tts, "Yedek yol."))
    assert s.usage.tts["calls"] == 1                              # başarısız akış faturalanmadı, yedek bir kez sayıldı
    assert not any(e["type"] == "error" for e in events)


def test_empty_stream_falls_back(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True, empty=True)
    s, out, _ = session(tmp_path, monkeypatch, tts)
    speak(s, "Boş.")
    assert tts.synth_calls == ["Boş."] and s.stats["tts_stream_fallbacks"] == 1 and out.pushed


def test_error_after_first_chunk_ends_sentence_cleanly_and_continues(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True, fail_after=2)
    s, out, events = session(tmp_path, monkeypatch, tts)
    speak(s, "Birinci cümle. İkinci cümle.")
    assert tts.synth_calls == [] and len(tts.stream_calls) == 2       # yedek yok; ikinci cümle de akışla denendi
    assert s.stats["tts_stream_errors"] == 2
    assert out.pushed and out.ended == 1
    assert any(e["type"] == "turn" for e in events) and not any(e["type"] == "error" for e in events)
    assert s.usage.tts["calls"] == 2


def test_multiple_sentences_stream_in_order(tmp_path, monkeypatch):
    tts = StreamTTS(streaming=True)
    s, out, _ = session(tmp_path, monkeypatch, tts)
    text = "Bir iki. Üç dört beş! Altı?"
    speak(s, text)
    from backend.app.voice.session import split_sentences
    assert tts.stream_calls == [__import__("backend.app.trnorm", fromlist=["x"]).normalize(x) for x in split_sentences(text)]
    got = np.concatenate(out.pushed)
    want = np.concatenate([expected_pcm(tts, x) for x in split_sentences(text)])
    assert len(got) == len(want) and np.max(np.abs(got.astype(int) - want.astype(int))) <= 1


def test_barge_in_mid_stream_stops_reading_and_pushing(tmp_path, monkeypatch):
    gate = threading.Event()
    tts = StreamTTS(streaming=True, gate=gate, chunk=1200)
    s, out, events = session(tmp_path, monkeypatch, tts)

    async def go():
        turn = s._next_turn()
        task = asyncio.get_running_loop().create_task(s._speak_turn("Uzun bir cümle. Ve bir tane daha.", turn, time.perf_counter(),
                                                                     rec={"turn": turn}))
        for _ in range(200):
            if out.pushed:
                break
            await asyncio.sleep(0.005)
        assert s.state == "speaking"
        s._barge_in()                                   # müşteri araya girdi
        gate.set()
        await asyncio.wait_for(task, 2)
        n = len(out.pushed)
        await asyncio.sleep(0.1)
        return n
    n_after = asyncio.run(go())
    assert n_after == 0 and out.pushed == []           # flush sonrası hiçbir parça itilmedi
    for _ in range(100):
        if tts.closed:
            break
        time.sleep(0.01)
    assert tts.closed == 1 and tts.yielded <= 3           # okuyucu durdu: 20 parçanın çoğu okunmadı
    assert len(tts.stream_calls) == 1                     # ikinci cümle istenmedi
    assert not any(e["type"] == "turn" for e in events)   # eski davranış: kesilen tur kaydı yazılmaz
    assert s.usage.tts["calls"] == 1                      # gönderilen karakter faturalanır (eski yolla aynı)


def test_close_during_stream_stops_the_reader(tmp_path, monkeypatch):
    gate = threading.Event()
    tts = StreamTTS(streaming=True, gate=gate)
    s, out, _ = session(tmp_path, monkeypatch, tts)

    async def go():
        turn = s._next_turn()
        s._spawn(s._speak_turn("Kapanış testi.", turn, time.perf_counter(), rec={"turn": turn}))
        for _ in range(200):
            if out.pushed:
                break
            await asyncio.sleep(0.005)
        await s.close()
        gate.set()
    asyncio.run(go())
    for _ in range(100):
        if tts.closed:
            break
        time.sleep(0.01)
    assert tts.closed == 1 and not s._tts_streams


def test_streaming_flag_off_uses_old_path_even_if_provider_can_stream(tmp_path, monkeypatch):
    tts = StreamTTS()                                     # streaming seçeneği yok (A1 gibi)
    s, out, _ = session(tmp_path, monkeypatch, tts)
    speak(s, "Eski yol.")
    assert tts.stream_calls == [] and tts.synth_calls == ["Eski yol."]
    assert len(out.pushed) == 1 and np.array_equal(out.pushed[0], expected_pcm(tts, "Eski yol."))
