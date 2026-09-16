"""Offline response diagnostics preserve native calls and expose no credential-bearing text."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

from famou.runtime import ModelTurn, OpenAICompatibleRuntime, ToolCall

REPO = Path(__file__).resolve().parents[1]
BASE_PATH = REPO / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py"
HELPER = REPO / "specs/115-isolated-intake-acceptance/measurement/response_guard.py"


@pytest.fixture
def modules(monkeypatch):
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    def forbidden(*args, **kwargs):
        raise AssertionError("test must not access native network transport")

    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)
    base = load("runtime_guard", BASE_PATH)
    return base, load("measurement115_response_guard", HELPER)


def setup_guard(modules, tmp_path, **kwargs):
    base, response = modules
    provider = base.ProviderConfiguration("https://offline.invalid/v1", "exact-credential-123", "app-model")
    guard = response.RuntimeGuard(provider, "fixture-model", tmp_path / "calls.jsonl", **kwargs)
    runtime = OpenAICompatibleRuntime(provider.endpoint, "fixture-model", provider.api_key)
    return guard, runtime


def turn(text="fixture assistant text", *, usage=True):
    return ModelTurn(text, tool_calls=(ToolCall("call-1", "read_file", {"path": "input.json"}),),
                     response_model="fixture-model", usage={
                         "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
                     } if usage else None)


def saved(guard, index=1):
    return json.loads((guard.journal_path.parent / "responses" / f"response-{index:03d}.json").read_text())


def test_exact_native_arguments_turn_and_base_accounting_preserved(modules, tmp_path):
    guard, runtime = setup_guard(modules, tmp_path)
    messages = [{"role": "user", "content": "fixed task"}]
    tools = ({"type": "function", "function": {"name": "read_file"}},)
    expected, calls = turn(), []

    def native(model, supplied_messages, supplied_tools, timeout):
        calls.append((model, supplied_messages, supplied_tools, timeout))
        assert model is runtime and supplied_messages is messages and supplied_tools is tools
        return expected

    assert guard.complete(native, runtime, messages, tools, 20) is expected
    assert guard.complete(native, runtime, messages, tools, 15) is expected
    assert [call[-1] for call in calls] == [20, 15]
    assert guard.snapshot()["provider_requests"] == guard.snapshot()["finished_requests"] == 2
    assert guard.snapshot()["known_usage"]["total_tokens"] == 10
    assert guard.snapshot()["response_diagnostics"] == {"captured": 2, "unavailable": 0}
    assert saved(guard, 1)["request_index"] == 1 and saved(guard, 2)["request_index"] == 2
    assert saved(guard)["redacted_prefix"] == expected.text
    assert saved(guard)["tool_call_count"] == 1
    assert stat.S_IMODE((tmp_path / "responses").stat().st_mode) == 0o700


def test_redacts_known_key_and_native_secret_patterns_before_utf8_prefix_limit(modules, tmp_path, capsys):
    guard, runtime = setup_guard(modules, tmp_path)
    original = (runtime.api_key + " sk-secretvalue12345678 Bearer bearer-token-123456 "
                "api_key=another-private-value\n" + "界" * 24_000)
    expected = turn(original)
    assert guard.complete(lambda *args: expected, runtime, []) is expected
    record = saved(guard)
    prefix = record["redacted_prefix"]
    for secret in (runtime.api_key, "sk-secretvalue12345678", "bearer-token-123456", "another-private-value"):
        assert secret not in json.dumps(record)
    assert prefix.startswith("[REDACTED] [REDACTED] [REDACTED] [REDACTED]\n")
    assert record["text_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert record["text_utf8_bytes"] == len(original.encode())
    assert record["redacted_prefix_utf8_bytes"] == len(prefix.encode()) <= 64 * 1024
    assert record["redaction_applied"] is record["truncated"] is True
    assert capsys.readouterr().out == ""
    assert runtime.api_key not in repr(guard) + json.dumps(guard.snapshot())


@pytest.mark.parametrize(("prefix", "stage"), [
    ("You are Lunar-Agent's algorithm contract compiler.", "contract_compiler"),
    ("You are compiling one frozen local evaluator bundle", "evaluator_compiler"),
    ("You are an independent adversarial evaluator auditor.", "evaluator_auditor"),
    ("ordinary candidate request", "other"),
])
def test_stage_hint_is_diagnostic_only(modules, tmp_path, prefix, stage):
    guard, runtime = setup_guard(modules, tmp_path)
    expected = turn("invalid JSON compiler response")
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": prefix}]
    assert guard.complete(lambda *args: expected, runtime, messages) is expected
    assert saved(guard)["stage_hint"] == stage
    assert saved(guard)["redacted_prefix"] == expected.text


@pytest.mark.parametrize("usage", [True, False])
def test_diagnostic_write_failure_preserves_success_or_base_guard_error(
    modules, tmp_path, monkeypatch, usage,
):
    base, _ = modules
    guard, runtime = setup_guard(modules, tmp_path)
    expected, calls = turn(usage=usage), []

    def native(*args):
        calls.append(1)
        return expected

    def unavailable(*args):
        raise OSError("private filesystem error " + runtime.api_key)

    monkeypatch.setattr(guard, "_write_response", unavailable)
    if usage:
        assert guard.complete(native, runtime, []) is expected
    else:
        with pytest.raises(base.MeasurementRuntimeError, match="^usage_unavailable$"):
            guard.complete(native, runtime, [])
    assert calls == [1]
    snapshot = guard.snapshot()
    assert snapshot["response_diagnostics"] == {"captured": 0, "unavailable": 1}
    assert snapshot["usage_complete"] is usage
    assert runtime.api_key not in json.dumps(snapshot)


def test_http_or_parse_failure_adds_no_response_or_request(modules, tmp_path):
    base, _ = modules
    guard, runtime = setup_guard(modules, tmp_path)
    calls = []

    def failed(*args):
        calls.append(1)
        raise OSError("provider error " + runtime.api_key)

    for _ in range(2):
        with pytest.raises(base.MeasurementRuntimeError, match="^provider_error$"):
            guard.complete(failed, runtime, [])
    assert calls == [1] and not (tmp_path / "responses").exists()
    assert guard.snapshot()["response_diagnostics"] == {"captured": 0, "unavailable": 0}


def test_diagnostic_latency_cannot_reject_already_accounted_response(modules, tmp_path, monkeypatch):
    base, _ = modules
    now = [0.0]
    guard, runtime = setup_guard(modules, tmp_path, wall_seconds=10, clock=lambda: now[0])
    expected = turn()
    writer = guard._write_response

    def slow_write(path, payload):
        now[0] = 11.0
        writer(path, payload)

    monkeypatch.setattr(guard, "_write_response", slow_write)
    assert guard.complete(lambda *args: expected, runtime, []) is expected
    assert guard.snapshot()["stopped_reason"] is None
    with pytest.raises(base.MeasurementRuntimeError, match="attempt_deadline_reached"):
        guard.complete(lambda *args: expected, runtime, [])
    assert guard.snapshot()["provider_requests"] == 1


def test_installed_base_guard_uses_response_subclass_without_extra_model_call(modules, tmp_path, monkeypatch):
    base, _ = modules
    guard, _ = setup_guard(modules, tmp_path)
    calls, expected = [], turn()

    def native(*args):
        calls.append(1)
        return expected

    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", native)
    with base.installed_guard(guard):
        assert OpenAICompatibleRuntime().complete([]) is expected
    assert calls == [1] and saved(guard)["redacted_prefix"] == expected.text


@pytest.mark.parametrize("collision", ["existing_file", "directory_symlink"])
def test_existing_or_redirected_diagnostics_are_not_overwritten(modules, tmp_path, collision):
    guard, runtime = setup_guard(modules, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if collision == "directory_symlink":
        (tmp_path / "responses").symlink_to(elsewhere, target_is_directory=True)
    else:
        (tmp_path / "responses").mkdir(mode=0o700)
        (tmp_path / "responses/response-001.json").write_text("existing evidence")
    expected = turn()
    assert guard.complete(lambda *args: expected, runtime, []) is expected
    assert guard.snapshot()["response_diagnostics"] == {"captured": 0, "unavailable": 1}
    assert not list(elsewhere.iterdir())
    if collision == "existing_file":
        assert (tmp_path / "responses/response-001.json").read_text() == "existing evidence"
