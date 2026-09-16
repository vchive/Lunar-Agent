"""Offline enforcement of the real acceptance request denominator and spending stops."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from famou.http_transport import TransportResponse
from famou.runtime import ModelRequestFailure, ModelTurn, OpenAICompatibleRuntime

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py"
spec = importlib.util.spec_from_file_location("measurement113_runtime_guard", HELPER)
guard_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard_module
spec.loader.exec_module(guard_module)


@pytest.fixture
def provider():
    return guard_module.ProviderConfiguration(
        "https://offline.invalid/v1", "credential-never-published", "fixture-configured-model",
        "responses", "ultra",
    )


@pytest.fixture
def native_forbidden(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("test attempted real HTTP transport")
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)


def turn(*, model="fixture-requested-model", input_tokens=3, output_tokens=2):
    return ModelTurn("answer", response_model=model, usage={
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    })


def make_guard(tmp_path, provider, **kwargs):
    return guard_module.RuntimeGuard(
        provider, "fixture-requested-model", tmp_path / "requests.jsonl", **kwargs,
    )


def rows(guard):
    return [json.loads(line) for line in guard.journal_path.read_text().splitlines()]


def test_started_is_durable_before_call_and_all_roles_share_admission(
    tmp_path, provider, monkeypatch, native_forbidden,
):
    calls = []
    guard = make_guard(tmp_path, provider, max_requests=2)

    def fake(runtime, messages, tools=(), timeout=None):
        assert rows(guard)[-1]["kind"] == "request_started"
        calls.append((runtime.model, messages, tools, timeout))
        assert runtime.api_key == provider.api_key
        return turn()

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake)
    before = OpenAICompatibleRuntime.__init__
    with guard_module.installed_guard(guard):
        first, second = OpenAICompatibleRuntime(), OpenAICompatibleRuntime()
        original_messages = [{"role": "user", "content": "compiler task"}]
        assert first.complete(original_messages).text == "answer"
        assert second.complete([{"role": "user", "content": "auditor task"}], timeout=30).text
        with pytest.raises(guard_module.MeasurementRuntimeError, match="request_limit_reached"):
            first.complete([])
    assert OpenAICompatibleRuntime.__init__ is before
    assert OpenAICompatibleRuntime.complete is fake
    assert calls[0][1] is original_messages
    assert [call[3] for call in calls] == [180.0, 30]
    assert [row["kind"] for row in rows(guard)] == ["request_started", "request_finished"] * 2
    assert guard.snapshot()["provider_requests"] == guard.snapshot()["finished_requests"] == 2
    assert guard.snapshot()["known_usage"]["total_tokens"] == 10
    assert provider.api_key not in guard.journal_path.read_text()


def test_guard_calls_native_transport_once_without_changing_payload(tmp_path, provider, monkeypatch):
    guard = make_guard(tmp_path, provider)
    exchanges = []
    messages = [{"role": "user", "content": "fixed task"}]
    tool_schema = ({"type": "function", "function": {"name": "read_file"}},)

    def exchange(request, timeout):
        assert rows(guard)[-1]["kind"] == "request_started"
        exchanges.append((request, timeout))
        payload = {"choices": [{"message": {"content": "native answer"}}],
                   "model": "fixture-requested-model",
                   "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
        return TransportResponse(200, json.dumps(payload).encode())

    monkeypatch.setattr("famou.runtime.exchange", exchange)
    with guard_module.installed_guard(guard):
        observed = OpenAICompatibleRuntime().complete(messages, tool_schema, 45)
    assert len(exchanges) == 1
    request, timeout = exchanges[0]
    assert request.full_url == "https://offline.invalid/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + provider.api_key
    assert json.loads(request.data) == {
        "model": "fixture-requested-model", "messages": messages,
        "stream": False, "tools": list(tool_schema),
    }
    assert timeout == 45
    assert observed.text == "native answer" and observed.usage == turn().usage


@pytest.mark.parametrize("case", ["missing_usage", "invalid_usage", "model_mismatch", "model_missing"])
def test_unknown_usage_and_model_rejection_latch_without_retry(
    tmp_path, provider, monkeypatch, native_forbidden, case,
):
    guard = make_guard(tmp_path, provider)
    calls = []
    result = turn()
    if case == "missing_usage":
        result = ModelTurn("answer", response_model="fixture-requested-model")
    elif case == "invalid_usage":
        result = ModelTurn("answer", response_model="fixture-requested-model", usage={
            "input_tokens": True, "output_tokens": 2, "total_tokens": 3,
        })
    else:
        result = ModelTurn("answer", response_model=(provider.api_key if case == "model_mismatch"
                                                     else None), usage=turn().usage)

    def fake(*args, **kwargs):
        calls.append(1)
        return result

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake)
    with guard_module.installed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        for _ in range(2):
            with pytest.raises(guard_module.MeasurementRuntimeError):
                runtime.complete([])
    assert len(calls) == 1
    final = rows(guard)[-1]
    assert final["outcome"] == ("usage_unavailable" if "usage" in case else "response_model_mismatch")
    assert final["usage_complete"] is ("usage" not in case)
    assert final["usage"] == (None if "usage" in case else turn().usage)
    assert provider.api_key not in guard.journal_path.read_text()


@pytest.mark.parametrize("failure", ["typed", "generic", "interrupted"])
def test_failed_request_preserves_denominator_known_usage_and_no_provider_prose(
    tmp_path, provider, monkeypatch, native_forbidden, failure,
):
    guard = make_guard(tmp_path, provider)
    calls = []

    def fake(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return turn()
        if failure == "typed":
            raise ModelRequestFailure(provider.api_key, "http_error", 429)
        if failure == "interrupted":
            raise KeyboardInterrupt(provider.api_key)
        raise OSError(provider.api_key)

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake)
    with guard_module.installed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        runtime.complete([])
        for _ in range(2):
            with pytest.raises(guard_module.MeasurementRuntimeError, match="provider_error") as error:
                runtime.complete([])
            assert provider.api_key not in str(error.value)
    assert len(calls) == guard.requests == 2
    assert guard.snapshot()["known_usage"]["total_tokens"] == 5
    assert guard.snapshot()["usage_complete"] is False
    assert rows(guard)[-1]["usage"] is None
    assert rows(guard)[-1]["response_status"] == (429 if failure == "typed" else None)
    assert provider.api_key not in guard.journal_path.read_text()


def test_triggering_token_overrun_is_observed_and_future_spending_stops(
    tmp_path, provider, monkeypatch, native_forbidden,
):
    guard = make_guard(tmp_path, provider, token_stop_threshold=9)
    calls = []

    def fake(*args, **kwargs):
        calls.append(1)
        return turn()

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake)
    with guard_module.installed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        runtime.complete([])
        for _ in range(2):
            with pytest.raises(guard_module.MeasurementRuntimeError,
                               match="observed_token_threshold_reached"):
                runtime.complete([])
    assert len(calls) == 2
    assert guard.snapshot()["known_usage"]["total_tokens"] == 10
    assert guard.snapshot()["usage_complete"] is True
    assert rows(guard)[-1]["usage"] == turn().usage


def test_request_timeout_uses_remaining_attempt_wall_and_late_return_cannot_succeed(
    tmp_path, provider, monkeypatch, native_forbidden,
):
    now, timeouts = [10.0], []
    guard = make_guard(tmp_path, provider, wall_seconds=100, clock=lambda: now[0])
    now[0] = 95.0

    def fake(runtime, messages, tools=(), timeout=None):
        timeouts.append(timeout)
        now[0] = 111.0
        return turn()

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake)
    with guard_module.installed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        for _ in range(2):
            with pytest.raises(guard_module.MeasurementRuntimeError, match="attempt_deadline_reached"):
                runtime.complete([], timeout=60)
    assert timeouts == [15.0]
    assert guard.snapshot()["known_usage"]["total_tokens"] == 5
    assert guard.snapshot()["usage_complete"] is True


def test_before_call_deadline_or_changed_runtime_is_zero_provider_calls(
    tmp_path, provider, monkeypatch, native_forbidden,
):
    now = [0.0]
    guard = make_guard(tmp_path, provider, wall_seconds=2, clock=lambda: now[0])
    with guard_module.installed_guard(guard):
        runtime = OpenAICompatibleRuntime()
        now[0] = 2.0
        with pytest.raises(guard_module.MeasurementRuntimeError, match="attempt_deadline_reached"):
            runtime.complete([])
    assert guard.requests == 0 and rows(guard) == []
    second = make_guard(tmp_path / "second", provider)
    with guard_module.installed_guard(second):
        runtime = OpenAICompatibleRuntime()
        runtime.model = "different-model"
        with pytest.raises(guard_module.MeasurementRuntimeError, match="runtime_registration_mismatch"):
            runtime.complete([])
    assert second.requests == 0 and rows(second) == []


def test_credentials_live_only_in_runtime_memory_while_cli_executes(
    tmp_path, provider, monkeypatch, native_forbidden,
):
    monkeypatch.setenv("FAMOU_API_KEY", "ambient-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-other-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-third-secret")
    monkeypatch.setenv("FAMOU_MODEL", "ambient-model")
    guard = make_guard(tmp_path, provider)
    with guard_module.installed_guard(guard):
        assert not any(key.startswith(("FAMOU_API", "OPENAI_", "ANTHROPIC_", "FAMOU_MODEL"))
                       for key in os.environ)
        runtime = OpenAICompatibleRuntime()
        assert runtime.api_key == provider.api_key
        assert runtime.model == "fixture-requested-model"
        with pytest.raises(guard_module.MeasurementRuntimeError, match="runtime_registration_mismatch"):
            OpenAICompatibleRuntime(model="ambient-model")
    assert os.environ["FAMOU_API_KEY"] == "ambient-secret"
    assert provider.api_key not in repr(provider)
    assert provider.api_key not in json.dumps(provider.safe_metadata("fixture-requested-model"))


def test_existing_journal_rejects_new_attempt_without_truncation(tmp_path, provider):
    guard = make_guard(tmp_path, provider)
    guard.journal_path.write_text('historical-ledger\n')
    with pytest.raises(FileExistsError):
        make_guard(tmp_path, provider)
    assert guard.journal_path.read_text() == 'historical-ledger\n'


def test_journal_failure_prevents_provider_admission(tmp_path, provider, monkeypatch, native_forbidden):
    guard = make_guard(tmp_path, provider)

    def unavailable(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(os, "fsync", unavailable)
    with guard_module.installed_guard(guard), pytest.raises(
        guard_module.MeasurementRuntimeError, match="request_journal_unavailable",
    ):
        OpenAICompatibleRuntime().complete([])
    assert guard.requests == 0


def fixture_cc_switch(tmp_path, *, endpoint="https://offline.invalid/v1"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "settings.json").write_text(json.dumps({"currentProviderCodex": "fixture"}))
    config = {
        "config": 'model = "configured-model"\nmodel_provider = "custom"\n'
                  'model_reasoning_effort = "ultra"\n[model_providers.custom]\n'
                  f'base_url = "{endpoint}"\nwire_api = "responses"\n',
        "auth": {"OPENAI_API_KEY": "fixture-secret-never-print"},
    }
    with sqlite3.connect(tmp_path / "cc-switch.db") as connection:
        connection.execute("CREATE TABLE providers (app_type TEXT, id TEXT, settings_config TEXT)")
        connection.execute("INSERT INTO providers VALUES (?, ?, ?)",
                           ("codex", "fixture", json.dumps(config)))
    return tmp_path


def test_provider_loader_pins_selected_gateway_and_explicit_model_without_claude(tmp_path):
    root = fixture_cc_switch(tmp_path / "cc")
    before = (root / "cc-switch.db").read_bytes()
    provider = guard_module.load_provider(root, requested_model="glm-5.2")
    metadata = provider.safe_metadata("glm-5.2")
    assert metadata["configured_model"] == "configured-model"
    assert metadata["requested_model"] == "glm-5.2"
    assert metadata["native_wire_api"] == "chat_completions"
    assert provider.api_key not in repr(provider) + json.dumps(metadata)
    assert guard_module.load_provider(root, requested_model="glm-5.2", expected=metadata) == provider
    assert (root / "cc-switch.db").read_bytes() == before
    for key in ("endpoint_sha256", "configured_model", "requested_model"):
        wrong = {**metadata, key: "changed"}
        with pytest.raises(guard_module.MeasurementRuntimeError, match="provider_registration_mismatch"):
            guard_module.load_provider(root, requested_model="glm-5.2", expected=wrong)


@pytest.mark.parametrize("endpoint", [
    "https://user:secret@offline.invalid/v1", "https://offline.invalid/v1?token=secret",
    "https://offline.invalid/v1#secret", "file:///tmp/provider",
])
def test_provider_loader_refuses_embedded_credentials_with_fixed_diagnostic(tmp_path, endpoint):
    root = fixture_cc_switch(tmp_path / "cc", endpoint=endpoint)
    with pytest.raises(guard_module.MeasurementRuntimeError,
                       match="^provider_configuration_unavailable$"):
        guard_module.load_provider(root, requested_model="glm-5.2")
