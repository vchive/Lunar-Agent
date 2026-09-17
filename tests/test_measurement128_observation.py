"""Offline evidence that the 128 observer preserves frozen request accounting and transport."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from urllib.request import Request

import pytest

import famou.runtime as runtime_module
from famou.http_transport import TransportFailure, TransportObservation, TransportResponse
from famou.runtime import ModelTurn, OpenAICompatibleRuntime

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "specs/128-format-admission-diagnostic/measurement/observation.py"
spec = importlib.util.spec_from_file_location("measurement128_observation_test", HELPER)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
MODEL = "fixture-requested-model"
MESSAGES = [{"role": "system", "content": "PRIVATE SYSTEM"},
            {"role": "user", "content": "PRIVATE TASK 中"}]


@pytest.fixture
def provider():
    return module.ProviderConfiguration("https://offline.invalid/v1", "private-credential", MODEL)


def make_guard(path, provider, **kwargs):
    return module.RuntimeGuard(provider, MODEL, path / "calls.jsonl", **kwargs)


def turn(text="native answer", usage=True):
    return ModelTurn(text, response_model=MODEL, usage=(
        {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5} if usage else None
    ))


def response(text="native answer", *, detail=None, usage=True):
    body = {"choices": [{"message": {"content": text}}], "model": MODEL}
    if usage:
        body["usage"] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    return TransportResponse(200, json.dumps(body).encode(), detail)


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def sidecar(guard):
    return read_rows(guard.journal_path.parent / "transport.jsonl")


def test_loader_uses_unique_module_without_search_path_mutation():
    before = list(sys.path)
    shared = module._load_shared_runtime()
    assert shared is module._shared
    assert sys.path == before
    assert shared.__name__ == "_lunar_measurement128_frozen113_runtime_guard"
    assert Path(shared.__file__).resolve() == (
        ROOT / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py"
    )
    assert issubclass(module.RuntimeGuard, shared.RuntimeGuard)
    assert module.load_provider is shared.load_provider


def test_success_payload_sequence_hashes_and_legacy_ledger_are_unchanged(
    tmp_path, provider, monkeypatch,
):
    requests = []
    detail = TransportObservation("response_headers_received", 1, 17)
    native_response = response(detail=detail)

    def exchange(request, timeout):
        requests.append((request, timeout))
        return native_response

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    fixed_clock = lambda: 100.0
    observed = make_guard(tmp_path / "observed", provider, clock=fixed_clock, max_requests=2)
    legacy = module.BaseRuntimeGuard(provider, MODEL, tmp_path / "base/calls.jsonl",
                                     clock=fixed_clock, max_requests=2)
    for guard, context in ((observed, module.observed_guard), (legacy, module._shared.installed_guard)):
        with context(guard):
            runtime = OpenAICompatibleRuntime()
            assert runtime.complete(MESSAGES, timeout=42).text == "native answer"
            assert runtime.complete(MESSAGES, timeout=23).text == "native answer"
            with pytest.raises(module.MeasurementRuntimeError, match="request_limit_reached"):
                runtime.complete(MESSAGES)
    assert observed.journal_path.read_bytes() == legacy.journal_path.read_bytes()
    assert [timeout for _, timeout in requests] == [42, 23, 42, 23]
    expected = json.dumps({"model": MODEL, "messages": MESSAGES, "stream": False},
                          ensure_ascii=False).encode()
    assert all(request.data == expected for request, _ in requests)
    assert all(request.get_header("Authorization") == "Bearer " + provider.api_key
               for request, _ in requests)
    rows = sidecar(observed)
    assert [row["request_index"] for row in rows] == [1, 2]
    assert [row["stage"] for row in rows] == ["evaluator_compiler", "evaluator_auditor"]
    for row in rows:
        assert row["request_body_bytes"] == len(expected)
        assert row["request_sha256"] == hashlib.sha256(expected).hexdigest()
        assert row["message_count"] == 2 and row["message_roles"] == ["system", "user"]
        assert row["tool_count"] == 0 and row["exchange_count"] == 1
        assert row["outcome"] == "response" and row["status"] == 200
        assert row["response_body_bytes"] == len(native_response.body)
        assert row["response_body_sha256"] == hashlib.sha256(native_response.body).hexdigest()
        assert row["transport_observation"] == {
            "last_milestone": "response_headers_received", "http_exchange_index": 1,
            "elapsed_ms": 17,
        }
    public = (observed.journal_path.read_text()
              + (observed.journal_path.parent / "transport.jsonl").read_text())
    for secret in (provider.endpoint, provider.api_key, "PRIVATE SYSTEM", "PRIVATE TASK", "native answer"):
        assert secret not in public
    assert observed.snapshot()["transport_diagnostics"] == {"captured": 2, "unavailable": 0}


@pytest.mark.parametrize("failed", [False, True])
def test_exchange_returns_or_rethrows_the_identical_object_and_restores(
    tmp_path, provider, monkeypatch, failed,
):
    expected = (TransportFailure(observation=TransportObservation("connect", 1, 10))
                if failed else response())
    seen = []

    def exchange(request, timeout):
        seen.append((request, timeout))
        if failed:
            raise expected
        return expected

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    before_init, before_complete = OpenAICompatibleRuntime.__init__, OpenAICompatibleRuntime.complete
    guard = make_guard(tmp_path, provider)
    request = Request("http://127.0.0.1/", data=b"opaque body")
    with module.observed_guard(guard):
        assert "OPENAI_API_KEY" not in os.environ
        if failed:
            with pytest.raises(TransportFailure) as caught:
                runtime_module.exchange(request, 19)
            assert caught.value is expected
        else:
            assert runtime_module.exchange(request, 19) is expected
    assert seen == [(request, 19)]
    assert runtime_module.exchange is exchange
    assert OpenAICompatibleRuntime.__init__ is before_init
    assert OpenAICompatibleRuntime.complete is before_complete
    assert os.environ["OPENAI_API_KEY"] == "environment-secret"
    assert guard.snapshot()["provider_requests"] == 0
    assert not (tmp_path / "transport.jsonl").exists()


def test_timeout_preserves_unknown_usage_and_sanitized_detail(tmp_path, provider, monkeypatch):
    failure = TransportFailure(reason="transport_timeout", cause="timeout",
                               observation=TransportObservation("wait_response_headers", 1, 123))
    calls = []

    def exchange(request, timeout):
        calls.append(1)
        raise failure

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        for _ in range(2):
            with pytest.raises(module.MeasurementRuntimeError, match="provider_error"):
                runtime.complete(MESSAGES)
    assert calls == [1]
    assert guard.snapshot()["known_usage"]["total_tokens"] == 0
    assert guard.snapshot()["usage_complete"] is False
    assert guard.snapshot()["response_diagnostics"] == {"captured": 0, "unavailable": 0}
    row, = sidecar(guard)
    assert row["status"] is None and row["outcome"] == "failure"
    assert row["failure_reason"] == "transport_timeout" and row["failure_phase"] == "open_response"
    assert row["transport_observation"]["last_milestone"] == "wait_response_headers"
    finished = read_rows(guard.journal_path)[1]
    assert finished["usage"] is None and finished["failure_reason"] == "transport_timeout"
    assert set(finished["observation"]) == {"phase", "elapsed_ms", "request_timeout_ms"}
    assert "transport_observation" not in finished


@pytest.mark.parametrize("detail", [None, {"private": "SECRET"},
                                    TransportObservation("SECRET", 1, 0),
                                    TransportObservation("connect", True, 0)])
def test_missing_or_invalid_detail_never_changes_native_success(
    tmp_path, provider, monkeypatch, detail,
):
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: response(detail=detail))
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard):
        assert OpenAICompatibleRuntime().complete(MESSAGES).text == "native answer"
    assert sidecar(guard)[0]["transport_observation"] is None
    assert "SECRET" not in (tmp_path / "transport.jsonl").read_text()


def test_http_error_body_is_only_hashed_and_never_captured_as_assistant_text(
    tmp_path, provider, monkeypatch,
):
    body = ("PRIVATE ERROR BODY " + provider.api_key).encode()
    failure = TransportFailure("read_http_error_body", "http_error", 429, "http_error", body,
                               TransportObservation("response_headers_received", 1, 7))

    def exchange(*args):
        raise failure

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard), pytest.raises(module.MeasurementRuntimeError):
        OpenAICompatibleRuntime().complete(MESSAGES)
    row, = sidecar(guard)
    assert row["outcome"] == "failure" and row["status"] == 429
    assert row["response_body_bytes"] == len(body)
    assert row["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert row["failure_phase"] == "read_http_error_body"
    assert row["failure_reason"] == "http_error"
    assert not (tmp_path / "responses").exists()
    for path in (guard.journal_path, tmp_path / "transport.jsonl"):
        assert provider.api_key not in path.read_text() and "PRIVATE ERROR BODY" not in path.read_text()


def test_invalid_json_body_is_observed_but_not_retained(tmp_path, provider, monkeypatch):
    raw = b"private malformed response"
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: TransportResponse(200, raw))
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard), pytest.raises(module.MeasurementRuntimeError):
        OpenAICompatibleRuntime().complete(MESSAGES)
    row, = sidecar(guard)
    assert row["outcome"] == "response" and row["status"] == 200
    assert row["response_body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert read_rows(guard.journal_path)[1]["failure_reason"] == "invalid_json"
    assert guard.snapshot()["usage_complete"] is False
    assert not (tmp_path / "responses").exists()
    assert "private malformed response" not in (tmp_path / "transport.jsonl").read_text()


def test_response_redaction_utf8_limit_and_explicit_private_permissions(
    tmp_path, provider, monkeypatch,
):
    text = provider.api_key + " sk-1234567890abcdefghijkl api_key=123456789SECRET " + "中" * 30_000
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: response(text))
    guard = make_guard(tmp_path, provider)
    old_umask = os.umask(0)
    try:
        with module.observed_guard(guard):
            result = OpenAICompatibleRuntime().complete(MESSAGES)
    finally:
        os.umask(old_umask)
    assert result.text == text
    path = tmp_path / "responses/response-001.json"
    capture = json.loads(path.read_text())
    assert capture["stage_hint"] == "evaluator_compiler"
    assert capture["text_utf8_bytes"] == len(text.encode())
    assert capture["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert capture["redaction_applied"] and capture["truncated"]
    assert capture["redacted_prefix_utf8_bytes"] <= 64 * 1024
    assert capture["redacted_prefix_utf8_bytes"] == len(capture["redacted_prefix"].encode())
    for secret in (provider.api_key, "sk-1234567890abcdefghijkl", "123456789SECRET"):
        assert secret not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "transport.jsonl").stat().st_mode) == 0o600


@pytest.mark.parametrize("rejection", ["unknown_usage", "token_threshold"])
def test_response_capture_after_accounting_even_when_guard_rejects_turn(
    tmp_path, provider, monkeypatch, rejection,
):
    native = response(usage=rejection != "unknown_usage")
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: native)
    guard = make_guard(tmp_path, provider, token_stop_threshold=5)
    with module.observed_guard(guard), pytest.raises(module.MeasurementRuntimeError):
        OpenAICompatibleRuntime().complete(MESSAGES)
    finished = read_rows(guard.journal_path)[1]
    assert finished["outcome"] == ("usage_unavailable" if rejection == "unknown_usage"
                                    else "observed_token_threshold_reached")
    assert guard.snapshot()["usage_complete"] is (rejection != "unknown_usage")
    assert guard.snapshot()["response_diagnostics"] == {"captured": 1, "unavailable": 0}


def test_failed_diagnostic_writes_and_clock_do_not_change_result(tmp_path, provider, monkeypatch):
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: response())
    guard = make_guard(tmp_path, provider)

    def unavailable(*args, **kwargs):
        assert read_rows(guard.journal_path)[-1]["outcome"] == "succeeded"
        raise OSError(provider.api_key)

    monkeypatch.setattr(module, "_write_private", unavailable)
    monkeypatch.setattr(module.time, "monotonic", lambda: float("nan"))
    with module.observed_guard(guard):
        assert OpenAICompatibleRuntime().complete(MESSAGES).text == "native answer"
    assert guard.snapshot()["response_diagnostics"] == {"captured": 0, "unavailable": 1}
    assert guard.snapshot()["transport_diagnostics"] == {"captured": 0, "unavailable": 1}
    assert guard.snapshot()["known_usage"]["total_tokens"] == 5
    assert guard.snapshot()["usage_complete"] is True


def test_no_exchange_and_invalid_roles_get_fixed_metadata_only(tmp_path, provider, monkeypatch):
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", lambda *_: turn())
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard):
        assert OpenAICompatibleRuntime().complete([{"role": provider.api_key, "content": "private"}])
    row, = sidecar(guard)
    assert row["message_roles"] == ["other"] and row["exchange_count"] == 0
    assert row["outcome"] == "unavailable" and row["request_sha256"] is None
    assert provider.api_key not in (tmp_path / "transport.jsonl").read_text()


def test_multiple_exchanges_do_not_silently_misattribute_one_transport(
    tmp_path, provider, monkeypatch,
):
    calls = []

    def exchange(*args):
        calls.append(1)
        return response()

    def native(*args):
        request = Request("http://127.0.0.1/", data=b"private")
        runtime_module.exchange(request, 5)
        runtime_module.exchange(request, 5)
        return turn()

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", native)
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard):
        assert OpenAICompatibleRuntime().complete(MESSAGES).text == "native answer"
    row, = sidecar(guard)
    assert calls == [1, 1] and row["exchange_count"] == 2
    assert row["outcome"] == "unavailable" and row["request_sha256"] is None
    assert row["transport_observation"] is None


@pytest.mark.parametrize("unsafe", ["directory_permissions", "symlink", "existing_response"])
def test_unsafe_private_capture_destination_never_overwrites_or_changes_native_result(
    tmp_path, provider, monkeypatch, unsafe,
):
    monkeypatch.setattr(runtime_module, "exchange", lambda *_: response())
    guard = make_guard(tmp_path, provider)
    root = tmp_path / "responses"
    if unsafe == "symlink":
        target = tmp_path / "untouched"
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir(mode=0o755 if unsafe == "directory_permissions" else 0o700)
        if unsafe == "existing_response":
            (root / "response-001.json").write_text("untouched")
    with module.observed_guard(guard):
        assert OpenAICompatibleRuntime().complete(MESSAGES).text == "native answer"
    assert guard.snapshot()["response_diagnostics"] == {"captured": 0, "unavailable": 1}
    if unsafe == "existing_response":
        assert (root / "response-001.json").read_text() == "untouched"
    else:
        assert not list(root.iterdir())


def test_context_exception_and_duplicate_install_restore_all_patches(tmp_path, provider, monkeypatch):
    exchange = runtime_module.exchange
    native_init, native_complete = OpenAICompatibleRuntime.__init__, OpenAICompatibleRuntime.complete
    guard = make_guard(tmp_path, provider)
    with pytest.raises(RuntimeError, match="fixture_failure"), module.observed_guard(guard):
        wrapped = runtime_module.exchange
        with (pytest.raises(module.MeasurementRuntimeError, match="guard_already_installed"),
              module.observed_guard(guard)):
            raise AssertionError("unreachable")
        assert runtime_module.exchange is wrapped
        raise RuntimeError("fixture_failure")
    assert runtime_module.exchange is exchange and not guard._installed
    assert OpenAICompatibleRuntime.__init__ is native_init
    assert OpenAICompatibleRuntime.complete is native_complete


def test_native_response_observation_without_socket_or_real_provider(tmp_path, monkeypatch):
    received = []

    def exchange(request, timeout):
        received.append((request.full_url, request.get_header("Authorization"), request.data))
        assert timeout == 5
        return response(detail=TransportObservation("response_headers_received", 1, 7))

    def forbidden(*args, **kwargs):
        pytest.fail("offline observer test attempted network")

    monkeypatch.setattr(runtime_module, "exchange", exchange)
    monkeypatch.setattr(runtime_module, "urlopen", forbidden)
    provider = module.ProviderConfiguration("https://offline.invalid/v1", "local-key", MODEL)
    guard = make_guard(tmp_path, provider)
    with module.observed_guard(guard):
        result = OpenAICompatibleRuntime().complete(MESSAGES, timeout=5)
    assert result.text == "native answer" and len(received) == 1
    assert received[0][:2] == ("https://offline.invalid/v1/chat/completions", "Bearer local-key")
    assert json.loads(received[0][2]) == {"model": MODEL, "messages": MESSAGES, "stream": False}
    row, = sidecar(guard)
    assert row["status"] == 200 and row["outcome"] == "response"
    assert row["request_sha256"] == read_rows(guard.journal_path)[0]["request_sha256"]
    assert row["transport_observation"]["last_milestone"] == "response_headers_received"
    assert row["transport_observation"]["http_exchange_index"] == 1
