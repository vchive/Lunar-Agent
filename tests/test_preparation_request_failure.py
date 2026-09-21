"""Request failures remain bounded, durable observations of recoverable preparation."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_automatic_solve_bundle import _fixture, _prepare
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_local_diagnostics import replace_payload
from test_preparation_recovery_cli import followup, observations, run_cli, runtime_calls, snapshot

from lunar_evolution import automatic_solve_bundle as automatic
from lunar_evolution import cli
from lunar_evolution.http_transport import TransportObservation
from lunar_evolution.runtime import (
    ModelFailureEvidence,
    ModelRequestFailure,
    ModelRequestObservation,
)
from lunar_evolution.store import Store

PRIVATE = "provider-private-response api_key=secret-132"
ROLES = ("compiler", "auditor")
OUTER_KEYS = {
    "schema_version", "parent_run_id", "attempt_id", "status", "stage",
    "error_category", "recoverable", "request_failure",
}


def request_error(reason="transport_timeout", status=None, phase="open_response"):
    error = ModelRequestFailure(PRIVATE, reason, status)
    error.observation = ModelRequestObservation(phase, 3000, 3000)
    error.transport_observation = TransportObservation(
        "wait_response_headers" if phase == "open_response" else "response_headers_received", 1, 2,
    )
    return error


def request_detail(error):
    return {
        "schema_version": "1", "reason": error.evidence.reason,
        "response_status": error.evidence.response_status,
        "request_observation": {
            "phase": error.observation.phase, "elapsed_ms": error.observation.elapsed_ms,
            "request_timeout_ms": error.observation.request_timeout_ms,
        } if error.observation is not None else None,
        "transport_observation": {
            "last_milestone": error.transport_observation.last_milestone,
            "http_exchange_index": error.transport_observation.http_exchange_index,
            "elapsed_ms": error.transport_observation.elapsed_ms,
        } if error.transport_observation is not None else None,
    }


def install_failure(monkeypatch, runtime, error, role):
    original, calls = runtime.run, []
    marker = "frozen local evaluator bundle" if role == "compiler" else "adversarial evaluator auditor"

    def fail(prompt, workspace, timeout=None):
        if marker in prompt:
            calls.append((role, timeout))
            raise error
        return original(prompt, workspace, timeout)

    monkeypatch.setattr(runtime, "run", fail)
    return original, calls


def failed_run(tmp_path, monkeypatch, capsys, *, role="compiler", error=None):
    error = request_error() if error is None else error
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original, calls = install_failure(monkeypatch, runtime, error, role)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    assert failed["status"] == "failed" and failed["run_status"] == "running"
    assert calls == [(role, 3.0)] and runtime.generator_calls == 0
    assert failed["input_request"] is None
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    return runtime, original, failed, store, workspace


def check_status(tmp_path, capsys, runtime, store, failed, workspace):
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    args = ["status", failed["run_id"], "--home", str(tmp_path / "home")]
    code, status, stderr = run_cli(capsys, [*args, "--json"])
    assert code == 0 and stderr == ""
    preparation = status["evolution"]["preparation"]
    native = automatic.automatic_bundle_preparation_status(store, failed["run_id"])
    assert {key: value for key, value in preparation.items()
            if key not in {"resume_hint", "request_failure_hint"}} == native
    assert cli.main(args) == 0
    text = capsys.readouterr()
    assert text.err == "" and PRIVATE not in text.out
    assert PRIVATE not in json.dumps(status)
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == calls
    return preparation, text.out


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("reason,status,phase", [
    ("transport_timeout", None, "open_response"),
    ("transport_timeout", 200, "read_response_body"),
    ("http_error", 503, "read_http_error_body"),
    ("invalid_json", 200, "validate_response"),
])
def test_request_failure_is_durable_bound_and_readonly_in_json_and_text(
    tmp_path, monkeypatch, capsys, role, reason, status, phase,
):
    error = request_error(reason, status, phase)
    runtime, _, failed, store, workspace = failed_run(
        tmp_path, monkeypatch, capsys, role=role, error=error,
    )
    preparation = failed["evolution"]["preparation"]
    records = observations(store, failed["run_id"])
    assert [row["type"] for row in records] == [
        "bundle_preparation_started", "bundle_preparation_failed",
    ]
    expected = {
        "schema_version": "3", "parent_run_id": failed["run_id"],
        "attempt_id": records[0]["payload"]["attempt_id"], "status": "failed",
        "stage": "evaluator_compile" if role == "compiler" else "evaluator_audit",
        "error_category": "runtime_error", "recoverable": True,
        "request_failure": request_detail(error),
    }
    assert set(records[1]["payload"]) == OUTER_KEYS
    assert records[1]["payload"] == expected
    assert {key: preparation[key] for key in OUTER_KEYS} == expected
    assert "resume" in preparation["resume_hint"]
    if reason == "transport_timeout":
        hint = preparation["request_failure_hint"].lower()
        assert "model request" in hint and ("timeout" in hint or "timed out" in hint)
        assert "remote completion" in hint and "usage" in hint and "unknown" in hint
        assert "new" in hint and "request" in hint and "explicit resume" in hint
    else:
        assert "request_failure_hint" not in preparation
    assert PRIVATE not in json.dumps([failed, records])
    assert (workspace / "solve/contract.json").is_file()
    assert not (workspace / "bundle-profile.json").exists()
    assert not (workspace / "evaluator-bundle").exists()
    assert not (workspace / "evolution-run").exists()
    assert not list(workspace.glob(".evaluator-bundle-*"))
    assert store.get_run(failed["run_id"]).status.value == "running"
    restored, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert restored == preparation
    assert f"preparation_request_failure: {reason}" in text
    assert "preparation_request_observation:" in text and phase in text
    assert "preparation_transport_observation:" in text
    assert error.transport_observation.last_milestone in text
    if status is not None:
        assert str(status) in text


CORRUPTIONS = (
    "detail_missing", "detail_null", "detail_string", "detail_extra", "detail_missing_key",
    "detail_version", "reason", "bool_status", "status_range", "phase_reason",
    "request_extra", "request_missing_key", "request_phase", "bool_elapsed", "negative_elapsed",
    "float_timeout", "large_timeout", "transport_extra", "transport_missing_key",
    "transport_milestone", "bool_exchange", "zero_exchange", "negative_transport_elapsed",
    "outer_version", "outer_extra", "outer_status", "outer_category", "outer_recoverable",
    "outer_stage", "parent", "attempt", "no_start", "duplicate_start", "intervening_start",
    "intervening_failure", "start_extra", "start_version", "start_stage", "start_status",
    "start_parent", "start_attempt", "start_category", "start_recoverable",
)


@pytest.mark.parametrize("corruption", CORRUPTIONS)
def test_unbound_or_malformed_persisted_request_failure_is_coarse_nonrecoverable(
    tmp_path, monkeypatch, capsys, corruption,
):
    runtime, _, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    start, event = observations(store, failed["run_id"])
    payload = copy.deepcopy(event["payload"])
    detail = payload["request_failure"]
    if corruption == "detail_missing":
        del payload["request_failure"]
    elif corruption in {"detail_null", "detail_string"}:
        payload["request_failure"] = None if corruption == "detail_null" else PRIVATE
    elif corruption == "detail_extra":
        detail["provider_error"] = PRIVATE
    elif corruption == "detail_missing_key":
        del detail["transport_observation"]
    elif corruption == "detail_version":
        detail["schema_version"] = "9"
    elif corruption == "reason":
        detail["reason"] = PRIVATE
    elif corruption in {"bool_status", "status_range"}:
        detail["response_status"] = True if corruption == "bool_status" else 600
    elif corruption == "phase_reason":
        detail["reason"] = "invalid_json"
    elif corruption.startswith("request_"):
        observation = detail["request_observation"]
        if corruption == "request_extra":
            observation["response"] = PRIVATE
        elif corruption == "request_missing_key":
            del observation["elapsed_ms"]
        else:
            observation["phase"] = PRIVATE
    elif corruption in {"bool_elapsed", "negative_elapsed", "float_timeout", "large_timeout"}:
        key, value = {
            "bool_elapsed": ("elapsed_ms", True), "negative_elapsed": ("elapsed_ms", -1),
            "float_timeout": ("request_timeout_ms", 3.0),
            "large_timeout": ("request_timeout_ms", 10**12 + 1),
        }[corruption]
        detail["request_observation"][key] = value
    elif corruption.startswith("transport_") or corruption in {
        "bool_exchange", "zero_exchange", "negative_transport_elapsed",
    }:
        observation = detail["transport_observation"]
        if corruption == "transport_missing_key":
            del observation["http_exchange_index"]
        else:
            key, value = {
                "transport_extra": ("response", PRIVATE),
                "transport_milestone": ("last_milestone", PRIVATE),
                "bool_exchange": ("http_exchange_index", True),
                "zero_exchange": ("http_exchange_index", 0),
                "negative_transport_elapsed": ("elapsed_ms", -1),
            }[corruption]
            observation[key] = value
    elif corruption in {"outer_version", "outer_extra", "outer_status", "outer_category",
                        "outer_recoverable", "outer_stage", "parent", "attempt"}:
        key, value = {
            "outer_version": ("schema_version", "1"), "outer_extra": ("source", PRIVATE),
            "outer_status": ("status", "started"), "outer_category": ("error_category", "validation_error"),
            "outer_recoverable": ("recoverable", False), "outer_stage": ("stage", "profile_publish"),
            "parent": ("parent_run_id", "another-parent"),
            "attempt": ("attempt_id", "preparation-" + "f" * 32),
        }[corruption]
        payload[key] = value
    elif corruption == "no_start":
        with store._connect() as connection:
            connection.execute("DELETE FROM events WHERE id = ?", (start["id"],))
    elif corruption in {"duplicate_start", "intervening_start", "intervening_failure"}:
        # Fix ordering explicitly so the failed record remains last, with a distinct predecessor.
        inserted = copy.deepcopy(start["payload"])
        if corruption != "duplicate_start":
            inserted["attempt_id"] = "preparation-" + "e" * 32
        kind = "bundle_preparation_started"
        if corruption == "intervening_failure":
            kind = "bundle_preparation_failed"
            inserted.update(status="failed", stage="evaluator_compile",
                            error_category="runtime_error", recoverable=True)
        with store._connect() as connection:
            connection.execute("UPDATE events SET created_at = ? WHERE id = ?", ("2100-01-01T00:00:00", start["id"]))
            connection.execute("UPDATE events SET created_at = ? WHERE id = ?", ("2100-01-01T00:00:02", event["id"]))
            connection.execute(
                "INSERT INTO events (id,run_id,task_id,type,payload,created_at) VALUES (?,?,?,?,?,?)",
                ("interposed-preparation", failed["run_id"], None, kind, json.dumps(inserted), "2100-01-01T00:00:01"),
            )
    else:
        altered = copy.deepcopy(start["payload"])
        key, value = {
            "start_extra": ("response", PRIVATE), "start_version": ("schema_version", "3"),
            "start_stage": ("stage", "evaluator_compile"), "start_status": ("status", "failed"),
            "start_parent": ("parent_run_id", "another-parent"),
            "start_attempt": ("attempt_id", "preparation-" + "e" * 32),
            "start_category": ("error_category", "runtime_error"),
            "start_recoverable": ("recoverable", True),
        }[corruption]
        altered[key] = value
        replace_payload(store, start, altered)
    replace_payload(store, event, payload)
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["schema_version"] == "1"
    assert preparation["status"] == "failed" and preparation["error_category"] == "validation_error"
    assert preparation["recoverable"] is False
    assert "request_failure" not in preparation and "resume_hint" not in preparation
    assert "request_failure_hint" not in preparation
    assert "preparation_request_failure:" not in text and "wait_response_headers" not in text


@pytest.mark.parametrize("source", ["plain_timeout", "wrapped", "subclass", "attribute", "bad_evidence"])
def test_unowned_or_indirect_request_evidence_retains_legacy_runtime_failure(
    tmp_path, monkeypatch, capsys, source,
):
    class DerivedRequestFailure(ModelRequestFailure):
        pass

    typed = request_error()
    if source == "plain_timeout":
        error = TimeoutError(PRIVATE)
    elif source == "wrapped":
        error = RuntimeError(PRIVATE)
        error.__cause__ = typed
    elif source == "subclass":
        error = DerivedRequestFailure(PRIVATE, "transport_timeout")
        error.observation, error.transport_observation = typed.observation, typed.transport_observation
    elif source == "attribute":
        error = RuntimeError(PRIVATE)
        error.evidence, error.observation = typed.evidence, typed.observation
    else:
        error = typed
        error.evidence = ModelFailureEvidence(PRIVATE, None)
    runtime, _, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys, error=error)
    preparation = failed["evolution"]["preparation"]
    assert preparation["schema_version"] == "1" and preparation["error_category"] == "runtime_error"
    assert preparation["recoverable"] is True and "request_failure" not in preparation
    assert "request_failure_hint" not in preparation
    assert PRIVATE not in json.dumps(observations(store, failed["run_id"]))
    restored, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert restored == preparation and "preparation_request_failure:" not in text


@pytest.mark.parametrize("detail", ["no_observations", "invalid_request", "invalid_transport"])
def test_bad_optional_typed_observation_drops_only_untrusted_detail(
    tmp_path, monkeypatch, capsys, detail,
):
    error = request_error()
    if detail == "no_observations":
        error.observation = error.transport_observation = None
    elif detail == "invalid_request":
        error.observation = ModelRequestObservation(PRIVATE, 3, 3)
    else:
        error.transport_observation = TransportObservation(PRIVATE, 1, 2)
    runtime, _, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys, error=error)
    preparation = failed["evolution"]["preparation"]
    assert preparation["schema_version"] == "3" and preparation["recoverable"] is True
    projected = preparation["request_failure"]
    assert projected["reason"] == "transport_timeout" and projected["response_status"] is None
    assert projected["transport_observation"] is None
    if detail != "invalid_transport":
        assert projected["request_observation"] is None
    else:
        assert projected["request_observation"] == request_detail(request_error())["request_observation"]
    restored, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert restored == preparation and "preparation_transport_observation:" not in text


@pytest.mark.parametrize("state", ["cancelled", "failed", "succeeded", "input_drift"])
def test_current_parent_and_inputs_suppress_stale_request_detail(tmp_path, monkeypatch, capsys, state):
    runtime, _, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    if state == "cancelled":
        assert store.cancel_run(failed["run_id"])
    elif state == "input_drift":
        (workspace / "data/raw/value").write_bytes(b"20")
    else:
        with store._connect() as connection:
            connection.execute("UPDATE runs SET status = ? WHERE id = ?", (state, failed["run_id"]))
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["error_category"] == ("cancelled" if state == "cancelled" else "validation_error")
    assert preparation["recoverable"] is False and "request_failure" not in preparation
    assert "request_failure_hint" not in preparation and "preparation_request_failure:" not in text


def test_new_incomplete_attempt_does_not_inherit_request_failure(tmp_path, monkeypatch, capsys):
    runtime, _, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    start = observations(store, failed["run_id"])[0]["payload"]
    store.append_event(failed["run_id"], "bundle_preparation_started", {
        **start, "attempt_id": "preparation-" + "a" * 32,
    })
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["status"] == "unknown" and preparation["error_category"] == "interrupted"
    assert preparation["recoverable"] is False and "request_failure" not in preparation
    assert "request_failure_hint" not in preparation and "preparation_request_failure:" not in text


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", ["resume", "solve"])
def test_explicit_resume_uses_contract_and_terminal_repeat_makes_no_requests(
    tmp_path, monkeypatch, capsys, role, command,
):
    runtime, original, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys, role=role)
    frozen_contract = (workspace / "solve/contract.json").read_bytes()
    monkeypatch.setattr(runtime, "run", original)
    continuation = followup(tmp_path, failed["run_id"], command)
    code, resumed, stderr = run_cli(capsys, continuation)
    assert code == 0 and stderr == "" and resumed["status"] == "succeeded"
    assert resumed["run_id"] == failed["run_id"]
    assert resumed["evolution"]["preparation"]["status"] == "prepared"
    assert "request_failure" not in resumed["evolution"]["preparation"]
    assert "request_failure_hint" not in resumed["evolution"]["preparation"]
    assert resumed["evolution"]["result"]["best_score"] == 9
    assert runtime.contract_calls == 1 and runtime.generator_calls == 4
    assert (workspace / "solve/contract.json").read_bytes() == frozen_contract
    assert len(observations(store, failed["run_id"], "bundle_preparation_started")) == 2
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, repeated, stderr = run_cli(capsys, continuation)
    assert code == 0 and stderr == "" and repeated["evolution"] == resumed["evolution"]
    assert snapshot(store, failed["run_id"], workspace) == before and runtime_calls(runtime) == calls


def test_verified_preparation_wins_over_later_stale_request_failure(tmp_path, monkeypatch, capsys):
    runtime, original, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    stale = observations(store, failed["run_id"])[1]["payload"]
    monkeypatch.setattr(runtime, "run", original)
    code, completed, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 0 and stderr == ""
    store.append_event(failed["run_id"], "bundle_preparation_failed", stale)
    preparation, text = check_status(tmp_path, capsys, runtime, store, completed, workspace)
    assert preparation["status"] == "prepared" and preparation["error_category"] is None
    assert preparation["recoverable"] is False and "request_failure" not in preparation
    assert "request_failure_hint" not in preparation and "preparation_request_failure:" not in text


@pytest.mark.parametrize("role", ROLES)
def test_answer_failure_preserves_request_diagnostics_and_parent(tmp_path, monkeypatch, capsys, role):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    code, waiting, stderr = run_cli(capsys, args)
    assert code == 0 and stderr == "" and waiting["status"] == "awaiting_input"
    _, calls = install_failure(monkeypatch, runtime, request_error(), role)
    code, failed, stderr = run_cli(capsys, [
        "answer", waiting["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ])
    assert code == 1 and stderr == "" and failed["run_id"] == waiting["run_id"]
    assert failed["status"] == "failed" and failed["run_status"] == "running"
    assert failed["input_request"] is None
    preparation = failed["evolution"]["preparation"]
    assert preparation["schema_version"] == "3" and preparation["recoverable"] is True
    assert preparation["request_failure"]["reason"] == "transport_timeout"
    assert "request_failure_hint" in preparation and len(calls) == 1
    assert PRIVATE not in json.dumps(failed)


@pytest.mark.parametrize("state", ["cancelled", "input_drift", "succeeded", "failed"])
def test_inflight_state_change_suppresses_request_details_before_durable_write(
    tmp_path, monkeypatch, state,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    calls = []

    def fail(prompt, workspace, timeout=None):
        calls.append(timeout)
        assert len(observations(controller.store, parent.id)) == 1
        if state == "cancelled":
            assert controller.store.cancel_run(parent.id)
        elif state == "input_drift":
            (parent.workspace / "data/raw/orders.csv").write_bytes(b"changed")
        else:
            with controller.store._connect() as connection:
                connection.execute("UPDATE runs SET status = ? WHERE id = ?", (state, parent.id))
        raise request_error()

    monkeypatch.setattr(runtime, "run", fail)
    with pytest.raises(automatic.AutomaticBundlePreparationError) as caught:
        _prepare(fixture)
    records = observations(controller.store, parent.id)
    assert [row["type"] for row in records] == [
        "bundle_preparation_started", "bundle_preparation_failed",
    ]
    recorded = records[1]["payload"]
    assert recorded == caught.value.preparation
    assert recorded["schema_version"] == "1" and recorded["status"] == "failed"
    assert recorded["stage"] == "evaluator_compile" and recorded["recoverable"] is False
    assert recorded["error_category"] == ("cancelled" if state == "cancelled" else "validation_error")
    assert recorded["attempt_id"] == records[0]["payload"]["attempt_id"]
    assert "request_failure" not in recorded and "request_failure_hint" not in recorded
    assert len(calls) == 1 and PRIVATE not in json.dumps(records)
    assert not (parent.workspace / "evaluator-bundle").exists()
    assert not (parent.workspace / "bundle-profile.json").exists()
