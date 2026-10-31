"""A1 gecikme işi, faz 1: uzak sağlayıcı çağrıları ana bilgisayar başına paylaşılan httpx.Client ile yapılır (keep-alive).

Gerçek ağ yok: yerel http.server bağlantı sayar. Hata mesajları (ProviderError) eski modül düzeyi httpx.post ile aynı biçimdedir.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.app.providers import remote
from backend.app.providers.base import ProviderError


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"    # keep-alive

    def setup(self):
        super().setup()
        with self.server.lock:
            self.server.connections += 1

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._send(200, b'{"ok": true}')

    def do_POST(self):
        body = self._body()
        srv = self.server
        with srv.lock:
            srv.posts += 1
            n = srv.posts
        if self.path.startswith("/drop-first") and n == 1:
            self.close_connection = True       # isteği okudu, yanıt vermeden kapattı (bayat bağlantı benzeri)
            self.connection.shutdown(2)
            return
        if self.path.startswith("/err"):
            self._send(500, b"sunucu patladi")
            return
        if self.path.startswith("/slow"):
            time.sleep(0.6)
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(5):
                part = bytes([i]) * 100
                try:
                    self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.05 if self.path.startswith("/stream-slow") else 0)
            self.wfile.write(b"0\r\n\r\n")
            return
        self._send(200, b'{"echo": %d}' % len(body))


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    srv.lock = threading.Lock()
    srv.connections = 0
    srv.posts = 0
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    t.start()
    remote.close_clients()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    remote.close_clients()
    srv.shutdown()
    srv.server_close()


def test_two_consecutive_posts_reuse_one_connection(server):
    srv, base = server
    assert remote._post(f"{base}/a", json={"x": 1}).json() == {"echo": 7}
    assert remote._post(f"{base}/b", content=b"abc").json() == {"echo": 3}
    assert srv.connections == 1 and srv.posts == 2


def test_get_post_and_stream_share_the_same_host_connection(server):
    srv, base = server
    remote._get(f"{base}/v")
    first, total, raw = remote._post_stream(f"{base}/stream", json={})
    remote._post(f"{base}/c", json={})
    assert raw == b"".join(bytes([i]) * 100 for i in range(5))
    assert 0 <= first <= total
    assert srv.connections == 1


def test_http_error_message_is_unchanged(server):
    _, base = server
    with pytest.raises(ProviderError) as e:
        remote._post(f"{base}/err", json={})
    assert str(e.value) == f"{base}/err HTTP 500: sunucu patladi"
    with pytest.raises(ProviderError) as e2:
        remote._post_stream(f"{base}/err", json={})
    assert str(e2.value) == f"{base}/err HTTP 500: sunucu patladi"


def test_connection_failure_message_is_unchanged():
    remote.close_clients()
    with pytest.raises(ProviderError) as e:
        remote._post("http://127.0.0.1:9/x", json={}, timeout=0.5)     # port 9: kapalı
    assert str(e.value).startswith("http://127.0.0.1:9/x çağrısı başarısız: ")
    with pytest.raises(ProviderError) as e2:
        remote._get("http://127.0.0.1:9/x", timeout=0.5)
    assert "çağrısı başarısız" in str(e2.value)
    with pytest.raises(ProviderError):
        remote._post_stream("http://127.0.0.1:9/x", json={}, timeout=0.5)


def test_per_call_timeout_is_respected(server):
    _, base = server
    t0 = time.perf_counter()
    with pytest.raises(ProviderError) as e:
        remote._post(f"{base}/slow", json={}, timeout=0.15)
    assert "çağrısı başarısız" in str(e.value) and time.perf_counter() - t0 < 0.55


def test_server_disconnect_without_response_is_retried_once_on_a_new_connection(server):
    srv, base = server
    assert remote._post(f"{base}/drop-first", json={}).status_code == 200
    assert srv.posts == 2 and srv.connections == 2


def test_concurrent_calls_from_threads_are_safe(server):
    srv, base = server
    errors, results = [], []

    def work():
        try:
            results.append(remote._post(f"{base}/p", json={"a": 1}).json()["echo"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert not errors and len(results) == 8
    assert srv.connections <= 8
    before = srv.connections
    remote._post(f"{base}/p", json={})       # boşta kalan bağlantılardan biri yeniden kullanılır
    assert srv.connections == before


def test_warm_connection_opens_the_pooled_connection(server):
    srv, base = server
    dt = remote.warm_connection(f"{base}/")
    assert isinstance(dt, float) and srv.connections == 1
    remote._post(f"{base}/x", json={})
    assert srv.connections == 1                # ısıtılan bağlantı ilk gerçek çağrıda kullanıldı


def test_warm_connection_never_raises():
    remote.close_clients()
    assert remote.warm_connection("http://127.0.0.1:9/", timeout=0.3) is None


def test_provider_prewarm_uses_its_host(monkeypatch):
    seen = []
    monkeypatch.setattr(remote, "warm_connection", lambda url, timeout=5.0: seen.append(url) or 0.01)
    assert remote.DeepgramSTT("nova-3").prewarm() == 0.01
    remote.AnthropicLLM("m").prewarm()
    remote.ElevenLabsTTS("eleven_flash_v2_5").prewarm()
    assert seen == ["https://api.deepgram.com/", "https://api.anthropic.com/", "https://api.elevenlabs.io/"]


def test_early_close_of_byte_stream_stops_reading(server):
    _, base = server
    gen = remote._stream_bytes(f"{base}/stream-slow", json={})
    t0 = time.perf_counter()
    assert next(gen) == bytes([0]) * 100
    gen.close()                                 # söz kesme: kalan gövde beklenmez
    assert time.perf_counter() - t0 < 0.2


def test_no_client_or_network_at_import_time():
    """Ayrı süreçte: httpx.Client ve soket bağlantısı yasaklıyken modül içe aktarılabilir (import anında ağ yok)."""
    import subprocess
    import sys
    code = ("import socket, httpx\n"
            "def boom(*a, **k): raise SystemExit('ag/istemci import sirasinda kullanildi')\n"
            "httpx.Client = boom; socket.create_connection = boom\n"
            "import backend.app.providers.remote as r\n"
            "assert r._clients == {}\n"
            "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr


def test_http2_only_when_h2_is_importable(monkeypatch, server):
    import httpx
    _, base = server
    made = {}
    real = httpx.Client

    def spy(*a, **k):
        made.update(k)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "Client", spy)
    remote.close_clients()
    remote._get(f"{base}/v")
    assert made["http2"] is remote.http2_available()
    assert made["limits"].keepalive_expiry == remote.KEEPALIVE_EXPIRY_S
