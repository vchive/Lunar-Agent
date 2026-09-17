"""Local wire fixtures for safe HTTP milestones; no provider requests are made."""

import base64
import json
import socket
import socketserver
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request

import pytest
import test_http_transport_tls as tls_fixtures
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_model_failure_evidence import SECRET

from famou import http_transport as transport

STALL_TIMEOUT = 0.6
local_certificate = tls_fixtures.local_certificate


@pytest.fixture(autouse=True)
def isolate_fixture_proxies(monkeypatch):
    clear_proxy_environment(monkeypatch)
    # An explicit environment projection also prevents use of host system proxies.
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def request(endpoint, body=None):
    return Request(
        endpoint,
        data=body if body is not None else json.dumps({"fixture": SECRET}).encode(),
        headers={"Authorization": "Bearer " + SECRET, "Content-Type": "application/json"},
        method="POST",
    )


def assert_milestone(outcome, milestone, index=1, timeout=STALL_TIMEOUT):
    observation = outcome.observation
    assert type(observation) is transport.TransportObservation
    safe = asdict(observation)
    assert set(safe) == {"last_milestone", "http_exchange_index", "elapsed_ms"}
    assert safe["last_milestone"] == milestone
    assert type(safe["http_exchange_index"]) is int
    assert safe["http_exchange_index"] == index
    assert type(safe["elapsed_ms"]) is int
    assert 0 <= safe["elapsed_ms"] <= timeout * 1000
    assert SECRET not in json.dumps(safe)
    assert "http://" not in json.dumps(safe) and "https://" not in json.dumps(safe)
    return observation


@pytest.mark.parametrize("mode,status,phase,reason,milestone", [
    ("headers", 200, "open_response", "transport_timeout", "wait_response_headers"),
    ("body", 200, "read_response_body", "transport_timeout", "response_headers_received"),
    ("error", 503, "read_http_error_body", "http_error", "response_headers_received"),
])
def test_real_http_stalls_retain_coarse_phase_and_last_local_milestone(
    mode, status, phase, reason, milestone,
):
    with local_http(mode, status) as (endpoint, calls):
        started = time.monotonic()
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request(endpoint + "/" + SECRET), STALL_TIMEOUT)
        elapsed = time.monotonic() - started
    error = caught.value
    assert len(calls) == 1
    assert error.phase == phase and error.reason == reason
    assert error.status == (None if mode == "headers" else status)
    assert_milestone(error, milestone)
    assert elapsed < 2
    assert SECRET not in str(error)


def test_success_milestone_keeps_exact_post_bytes_and_authorization():
    body = b'{"fixture":"UTF-8: \xe6\x9c\x88", "literal":"\\n"}\n'
    with local_http() as (endpoint, calls):
        result = transport.exchange(request(endpoint + "/private?token=" + SECRET, body), 2)
    assert result.status == 200
    assert json.loads(result.body) == {"choices": [{"message": {"content": "done"}}]}
    assert len(calls) == 1
    assert calls[0][0] == "/private?token=" + SECRET
    assert calls[0][1] == body
    assert calls[0][2]["Authorization"] == "Bearer " + SECRET
    assert calls[0][2]["Content-Type"] == "application/json"
    assert calls[0][2]["Content-Length"] == str(len(body))
    assert_milestone(result, "response_headers_received", timeout=2)


@contextmanager
def accepting_tcp_without_reading():
    """A small TCP receive window forces a large request to block in sendall."""
    stop = threading.Event()
    connections = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            connections.append(self.client_address)
            stop.wait(5)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler, bind_and_activate=False) as server:
        # Set the listening socket's buffer before the SYN so accepted connections inherit
        # a small advertised receive window. No fixture handler reads any request bytes.
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        server.server_bind()
        server.server_activate()
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}", connections
        finally:
            stop.set()
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_large_post_send_stall_is_distinct_from_waiting_for_response_headers():
    timeout = 2
    body = b"x" * (16 * 1024 * 1024)
    with accepting_tcp_without_reading() as (endpoint, connections):
        started = time.monotonic()
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request(endpoint, body), timeout)
        elapsed = time.monotonic() - started
    assert len(connections) == 1
    assert caught.value.phase == "open_response" and caught.value.status is None
    assert caught.value.reason == "transport_timeout"
    assert_milestone(caught.value, "send_request", timeout=timeout)
    assert elapsed < 4


def test_unlistened_local_port_never_reaches_send_request():
    # Holding a bound, non-listening socket reserves the port without allowing a
    # connection or any HTTP request; closing a listener first would introduce a race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request(endpoint), STALL_TIMEOUT)
    assert caught.value.phase == "open_response" and caught.value.status is None
    # Kernels may reject this connection immediately or silently drop its SYN.
    assert caught.value.reason in {"transport_error", "transport_timeout"}
    assert_milestone(caught.value, "connect")


@pytest.mark.parametrize("stage", ["startup", "dns"])
def test_worker_startup_and_dns_stalls_are_distinguished_without_http(monkeypatch, stage):
    if stage == "startup":
        setup = "import threading;threading.Event().wait(5);"
    else:
        setup = (
            "import socket,threading;"
            "socket.getaddrinfo=lambda *a,**kw: threading.Event().wait(5);"
        )
    code = setup + f"import runpy;runpy.run_path({transport.__file__!r},run_name='__main__')"
    monkeypatch.setattr(
        transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)],
    )
    with local_http() as (endpoint, calls), pytest.raises(transport.TransportFailure) as caught:
        transport.exchange(request(endpoint), STALL_TIMEOUT)
    assert calls == []
    assert caught.value.phase == "open_response" and caught.value.status is None
    assert caught.value.reason == "transport_timeout"
    if stage == "startup":
        assert caught.value.observation is None
    else:
        assert_milestone(caught.value, "connect")


@contextmanager
def accepting_tcp_without_tls():
    """Accept TCP and the client's TLS hello, then withhold the server handshake."""
    stop = threading.Event()
    hellos = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            try:
                hellos.append(self.request.recv(4096))
                stop.wait(3)
            except (TimeoutError, ConnectionResetError):
                pass

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            yield f"https://127.0.0.1:{server.server_address[1]}", hellos
        finally:
            stop.set()
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_tls_handshake_stall_does_not_claim_request_was_sent():
    with accepting_tcp_without_tls() as (endpoint, hellos):
        started = time.monotonic()
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request(endpoint), STALL_TIMEOUT)
        elapsed = time.monotonic() - started
    assert len(hellos) == 1 and hellos[0]
    assert caught.value.phase == "open_response" and caught.value.status is None
    assert caught.value.reason == "transport_timeout"
    assert_milestone(caught.value, "connect")
    assert elapsed < 2


@contextmanager
def stalled_connect_proxy():
    stop = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_CONNECT(self):
            calls.append((self.path, dict(self.headers)))
            stop.wait(3)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield server.server_port, calls
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_https_proxy_connect_stall_stays_in_connect_and_separates_authorization(monkeypatch):
    with stalled_connect_proxy() as (port, calls):
        monkeypatch.setenv("https_proxy", f"http://fixture:{SECRET}@127.0.0.1:{port}")
        started = time.monotonic()
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request("https://upstream.invalid/private"), STALL_TIMEOUT)
        elapsed = time.monotonic() - started
    assert len(calls) == 1 and calls[0][0] == "upstream.invalid:443"
    expected = "Basic " + base64.b64encode(("fixture:" + SECRET).encode()).decode()
    assert calls[0][1]["Proxy-Authorization"] == expected
    assert "Authorization" not in calls[0][1]
    assert caught.value.phase == "open_response" and caught.value.status is None
    assert caught.value.reason == "transport_timeout"
    assert_milestone(caught.value, "connect")
    assert elapsed < 2


def test_https_success_retains_standard_tls_trust_and_alpn(monkeypatch, local_certificate):
    certificate, key, _directory = local_certificate
    tls_fixtures.project_trust(monkeypatch, certificate)
    protocols = []
    with tls_fixtures.local_https(certificate, key, observed_protocols=protocols) as (endpoint, calls):
        result = transport.exchange(request(endpoint), 2)
    assert result.status == 200 and calls == ["/chat/completions"]
    assert protocols == ["http/1.1"]
    assert_milestone(result, "response_headers_received", timeout=2)


def test_untrusted_tls_failure_retains_connect_milestone(monkeypatch, local_certificate):
    certificate, key, _directory = local_certificate
    tls_fixtures.project_trust(monkeypatch, None)
    with tls_fixtures.local_https(certificate, key) as (endpoint, calls), pytest.raises(transport.TransportFailure) as caught:
        transport.exchange(request(endpoint), 2)
    assert calls == []
    assert caught.value.reason == "transport_error" and caught.value.status is None
    assert caught.value.phase == "open_response"
    assert_milestone(caught.value, "connect", timeout=2)


@contextmanager
def local_redirect(mode):
    stop = threading.Event()
    calls = []
    response_body = ("response: " + SECRET).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def record(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.command, self.path, body, dict(self.headers)))

        def send_fixture_headers(self, status, size, *, location=None):
            self.send_response(status)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(size))
            self.end_headers()

        def do_POST(self):
            self.record()
            try:
                if mode == "redirect_body":
                    raw = response_body * 100
                    self.send_fixture_headers(302, len(raw), location="/second")
                    for index in range(0, len(raw), 4):
                        if stop.wait(0.06):
                            return
                        self.wfile.write(raw[index:index + 4])
                        self.wfile.flush()
                else:
                    self.send_fixture_headers(302, 0, location="/second")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.record()
            if mode == "second_headers":
                stop.wait(3)
            try:
                self.send_fixture_headers(200, len(response_body))
                self.wfile.write(response_body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/first", calls, response_body
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("mode,milestone,index", [
    ("redirect_body", "response_headers_received", 1),
    ("second_headers", "wait_response_headers", 2),
])
def test_redirect_stalls_distinguish_intermediate_body_from_next_header_wait(mode, milestone, index):
    body = json.dumps({"literal": SECRET}).encode()
    with local_redirect(mode) as (endpoint, calls, _response_body):
        started = time.monotonic()
        with pytest.raises(transport.TransportFailure) as caught:
            transport.exchange(request(endpoint, body), STALL_TIMEOUT)
        elapsed = time.monotonic() - started
    assert len(calls) == index
    assert calls[0][:3] == ("POST", "/first", body)
    assert calls[0][3]["Authorization"] == "Bearer " + SECRET
    if index == 2:
        assert calls[1][:3] == ("GET", "/second", b"")
        assert "Content-Length" not in calls[1][3]
    assert caught.value.phase == "open_response" and caught.value.status is None
    assert caught.value.reason == "transport_timeout"
    assert_milestone(caught.value, milestone, index)
    assert elapsed < 2


def test_completed_redirect_preserves_get_and_response_bytes_without_observation_leakage():
    body = b"private request: " + SECRET.encode()
    with local_redirect("success") as (endpoint, calls, response_body):
        result = transport.exchange(request(endpoint, body), 2)
    assert result.status == 200 and result.body == response_body
    assert len(calls) == 2
    assert calls[0][:3] == ("POST", "/first", body)
    assert calls[1][:3] == ("GET", "/second", b"")
    assert "Content-Length" not in calls[1][3]
    assert_milestone(result, "response_headers_received", index=2, timeout=2)
