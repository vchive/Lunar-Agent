"""Public runtime HTTPS trust and deadline checks using only a local self-signed fixture."""

import json
import shutil
import ssl
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from famou.runtime import ModelRequestFailure, OpenAICompatibleRuntime


@pytest.fixture(scope="module")
def local_certificate(tmp_path_factory):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is needed only to generate a local TLS test certificate")
    directory = tmp_path_factory.mktemp("transport-tls-fixture")
    certificate, key = directory / "ca.pem", directory / "server.key"
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(certificate), "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    hashed = subprocess.check_output([
        openssl, "x509", "-hash", "-noout", "-in", str(certificate),
    ], text=True, timeout=5).strip()
    trust_directory = directory / "trust"
    trust_directory.mkdir()
    shutil.copyfile(certificate, trust_directory / f"{hashed}.0")
    return certificate, key, trust_directory


@contextmanager
def local_https(certificate, key, *, slow=False, observed_protocols=None):
    requests = []
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(self.path)
            if observed_protocols is not None:
                observed_protocols.append(self.connection.selected_alpn_protocol())
            body = json.dumps({"model": "fixture", "choices": [{"message": {"content": "done"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if slow:
                    for index in range(0, len(body), 2):
                        self.wfile.write(body[index:index + 2])
                        self.wfile.flush()
                        if stop.wait(0.04):
                            break
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    context.set_alpn_protocols(["http/1.1"])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}/chat/completions", requests
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def project_trust(monkeypatch, certificate, trust_directory=None):
    # urllib may cache an HTTPSHandler/context from an earlier fixture's trust configuration.
    monkeypatch.setattr("urllib.request._opener", None)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    if certificate is None:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    else:
        monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    if trust_directory is None:
        monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    else:
        monkeypatch.setenv("SSL_CERT_DIR", str(trust_directory))


@pytest.mark.parametrize("timeout", [None, 2])
def test_public_https_projects_ca_file_without_inheriting_keylog(
    tmp_path, monkeypatch, local_certificate, timeout,
):
    certificate, key, _directory = local_certificate
    project_trust(monkeypatch, certificate)
    keylog = tmp_path / "fixture-tls-keylog"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    with local_https(certificate, key) as (endpoint, calls):
        result = OpenAICompatibleRuntime(endpoint, "fixture", "LOCAL-FIXTURE-ONLY").complete(
            [], timeout=timeout,
        )
    assert result.text == "done" and calls == ["/chat/completions"]
    # The None path keeps caller urllib behavior; the bounded worker must not inherit key logging.
    assert keylog.exists() is (timeout is None)


def test_public_https_projects_hashed_ca_directory(monkeypatch, local_certificate):
    certificate, key, directory = local_certificate
    project_trust(monkeypatch, None, directory)
    with local_https(certificate, key) as (endpoint, calls):
        result = OpenAICompatibleRuntime(endpoint, "fixture", "LOCAL-FIXTURE-ONLY").complete(
            [], timeout=2,
        )
    assert result.text == "done" and calls == ["/chat/completions"]


@pytest.mark.parametrize("timeout", [None, 2])
def test_public_https_preserves_standard_library_http_alpn(
    monkeypatch, local_certificate, timeout,
):
    certificate, key, _directory = local_certificate
    project_trust(monkeypatch, certificate)
    protocols = []
    with local_https(certificate, key, observed_protocols=protocols) as (endpoint, calls):
        result = OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=timeout)
    assert result.text == "done" and calls == ["/chat/completions"]
    assert protocols == ["http/1.1"]


def test_public_https_rejects_untrusted_certificate(monkeypatch, local_certificate):
    certificate, key, _directory = local_certificate
    project_trust(monkeypatch, None)
    with local_https(certificate, key) as (endpoint, calls), pytest.raises(ModelRequestFailure) as caught:
        OpenAICompatibleRuntime(endpoint, "fixture", "LOCAL-FIXTURE-ONLY").complete([], timeout=2)
    assert calls == []
    assert caught.value.evidence.reason == "transport_error"
    assert caught.value.evidence.response_status is None


def test_public_https_trickle_stops_at_transport_deadline(monkeypatch, local_certificate):
    certificate, key, _directory = local_certificate
    project_trust(monkeypatch, certificate)
    with local_https(certificate, key, slow=True) as (endpoint, calls):
        started = time.monotonic()
        with pytest.raises(ModelRequestFailure) as caught:
            OpenAICompatibleRuntime(endpoint, "fixture", "LOCAL-FIXTURE-ONLY").complete([], timeout=0.3)
        elapsed = time.monotonic() - started
    assert calls == ["/chat/completions"]
    assert caught.value.evidence.reason == "transport_timeout"
    assert caught.value.evidence.response_status == 200
    assert caught.value.observation.phase == "read_response_body"
    assert elapsed < 1.5  # Allows startup/scheduling/cleanup, rejects the whole slow successful body.
