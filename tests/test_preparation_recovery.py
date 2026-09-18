"""Preparation observations are durable diagnostics, never evaluator authority."""

import json

import pytest
from test_automatic_solve_bundle import _fixture, _prepare, _snapshot

from famou import automatic_solve_bundle, evaluator_bundle
from famou.automatic_solve_bundle import (
    AutomaticBundlePreparationError,
    automatic_bundle_preparation_status,
)
from famou.evaluator_bundle import EvaluatorBundleError
from famou.evolution import EvolutionError
from famou.runtime import RuntimeResult


def _observations(controller, parent, kind=None):
    return [
        event for event in controller.store.list_events(parent.id)
        if event["type"].startswith("bundle_preparation_")
        and (kind is None or event["type"] == kind)
    ]


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
def test_runtime_failure_records_one_safe_attempt_and_explicit_resume_reuses_contract(
    tmp_path, monkeypatch, stage,
):
    fixture = _fixture(tmp_path)
    controller, parent, contract, runtime = fixture
    run = runtime.run
    calls = []
    secret = "api_key=do-not-persist-this-provider-text"

    def fail(prompt, workspace, timeout=None):
        assert len(_observations(controller, parent, "bundle_preparation_started")) == 1
        calls.append(prompt)
        if stage == "evaluator_compile" or "adversarial evaluator auditor" in prompt:
            raise TimeoutError(secret)
        return run(prompt, workspace, timeout)

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "run", fail)
        with pytest.raises(AutomaticBundlePreparationError) as caught:
            _prepare(fixture)

    observations = _observations(controller, parent)
    assert [event["type"] for event in observations] == [
        "bundle_preparation_started", "bundle_preparation_failed",
    ]
    started, failed = [event["payload"] for event in observations]
    assert started["attempt_id"] == failed["attempt_id"]
    assert failed == {
        "schema_version": "1", "parent_run_id": parent.id, "attempt_id": started["attempt_id"],
        "status": "failed", "stage": stage, "error_category": "runtime_error", "recoverable": True,
    }
    assert caught.value.preparation == failed
    assert automatic_bundle_preparation_status(controller.store, parent.id) == failed
    assert secret not in json.dumps(controller.store.list_events(parent.id))
    assert len(calls) == (1 if stage == "evaluator_compile" else 2)
    assert not (parent.workspace / "evaluator-bundle").exists()
    assert not (parent.workspace / "bundle-profile.json").exists()
    assert not (parent.workspace / "evolution-run").exists()
    current = controller.store.get_current_plan(parent.id)
    assert current.algorithm_problem == contract.to_dict()

    _prepare(fixture)

    assert len(_observations(controller, parent, "bundle_preparation_started")) == 2
    assert automatic_bundle_preparation_status(controller.store, parent.id) == {
        "schema_version": "1", "parent_run_id": parent.id, "attempt_id": None,
        "status": "prepared", "stage": "profile_publish", "error_category": None,
        "recoverable": False,
    }
    before = _snapshot(controller, parent)
    _prepare(fixture)
    assert _snapshot(controller, parent) == before


@pytest.mark.parametrize("stage", ["runtime", "profile"])
def test_interrupted_start_is_unknown_and_frozen_recovery_avoids_model_work(
    tmp_path, monkeypatch, stage,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture

    class Interrupted(BaseException):
        pass

    def stop(*args, **kwargs):
        raise Interrupted()

    with monkeypatch.context() as patch:
        if stage == "runtime":
            patch.setattr(runtime, "run", stop)
        else:
            patch.setattr(automatic_solve_bundle, "_write_profile", stop)
        with pytest.raises(Interrupted):
            _prepare(fixture)

    status = automatic_bundle_preparation_status(controller.store, parent.id)
    assert status["status"] == "unknown"
    assert status["error_category"] == "interrupted"
    assert status["recoverable"] is False
    assert len(_observations(controller, parent)) == 1
    assert (runtime.bundle_calls, runtime.audit_calls) == ((0, 0) if stage == "runtime" else (1, 1))
    if stage == "profile":
        assert (parent.workspace / "evaluator-bundle/manifest.json").is_file()

    _prepare(fixture)

    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert automatic_bundle_preparation_status(controller.store, parent.id)["status"] == "prepared"


@pytest.mark.parametrize("corruption", ["parent", "duplicate_start", "attempt"])
def test_corrupt_interrupted_start_cannot_open_another_attempt(tmp_path, monkeypatch, corruption):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    calls = []

    class Interrupted(BaseException):
        pass

    def stop(*args, **kwargs):
        calls.append("provider")
        raise Interrupted()

    monkeypatch.setattr(runtime, "run", stop)
    with pytest.raises(Interrupted):
        _prepare(fixture)
    assert calls == ["provider"]
    assert not _observations(controller, parent, "bundle_preparation_failed")
    start, = _observations(controller, parent, "bundle_preparation_started")
    payload = dict(start["payload"])
    if corruption == "parent":
        payload["parent_run_id"] = "different-parent"
    elif corruption == "attempt":
        payload["attempt_id"] = "invalid-attempt"
    else:
        assert controller.store.append_event(parent.id, "bundle_preparation_started", payload)
    with controller.store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), start["id"]))

    before = _snapshot(controller, parent)
    with pytest.raises(EvolutionError):
        _prepare(fixture)

    assert calls == ["provider"]
    expected_starts = 2 if corruption == "duplicate_start" else 1
    assert len(_observations(controller, parent, "bundle_preparation_started")) == expected_starts
    assert not _observations(controller, parent, "bundle_preparation_failed")
    assert _snapshot(controller, parent) == before


def test_malformed_response_is_recorded_without_becoming_runtime_retry(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    monkeypatch.setattr(runtime, "run", lambda *args: RuntimeResult("provider private prose"))

    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    assert caught.value.preparation["recoverable"] is False
    assert caught.value.preparation["error_category"] == "validation_error"
    assert "provider private prose" not in json.dumps(_observations(controller, parent))


@pytest.mark.parametrize("stage", [[], {}])
def test_malformed_schema_one_stage_is_validation_error_without_crash(tmp_path, stage):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    attempt_id = "attempt-malformed-stage"
    controller.store.append_event(parent.id, "bundle_preparation_started", {
        "parent_run_id": parent.id,
        "attempt_id": attempt_id,
        "status": "started",
        "stage": "preparation",
    })
    controller.store.append_event(parent.id, "bundle_preparation_failed", {
        "schema_version": "1",
        "parent_run_id": parent.id,
        "attempt_id": attempt_id,
        "status": "failed",
        "stage": stage,
        "error_category": "runtime_error",
        "recoverable": True,
    })

    status = automatic_bundle_preparation_status(controller.store, parent.id)

    assert status["status"] == "failed"
    assert status["error_category"] == "validation_error"
    assert status["recoverable"] is False
    before = len(_observations(controller, parent, "bundle_preparation_started"))
    with pytest.raises(EvolutionError):
        _prepare(fixture)
    assert len(_observations(controller, parent, "bundle_preparation_started")) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (0, 0)


def test_arbitrary_failure_prose_cannot_claim_runtime_retry(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, _ = fixture

    def fail(*args, **kwargs):
        raise EvaluatorBundleError("evaluator compiler failed: runtime_error")

    monkeypatch.setattr(automatic_solve_bundle, "compile_evaluator_bundle", fail)
    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    assert caught.value.preparation["recoverable"] is False
    assert automatic_bundle_preparation_status(controller.store, parent.id)["recoverable"] is False


@pytest.mark.parametrize("terminal_status", ["succeeded", "failed"])
def test_historical_runtime_failure_does_not_offer_retry_for_terminal_parent(
    tmp_path, monkeypatch, terminal_status,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture

    def fail(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(runtime, "run", fail)
    with pytest.raises(AutomaticBundlePreparationError):
        _prepare(fixture)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (terminal_status, parent.id))
    status = automatic_bundle_preparation_status(controller.store, parent.id)
    assert status["status"] == "failed"
    assert status["recoverable"] is False
    with pytest.raises(EvolutionError):
        _prepare(fixture)
    assert len(_observations(controller, parent, "bundle_preparation_started")) == 1


@pytest.mark.parametrize("change", ["cancel", "input"])
def test_concurrent_cancellation_or_input_drift_cannot_become_retryable_runtime_failure(
    tmp_path, monkeypatch, change,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture

    def fail(*args, **kwargs):
        if change == "cancel":
            controller.store.cancel_run(parent.id)
        else:
            (parent.workspace / "data/raw/orders.csv").write_text("changed")
        raise TimeoutError("private provider details")

    monkeypatch.setattr(runtime, "run", fail)
    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    category = "cancelled" if change == "cancel" else "validation_error"
    assert caught.value.preparation["error_category"] == category
    assert caught.value.preparation["recoverable"] is False
    before = _snapshot(controller, parent)
    with pytest.raises(EvolutionError):
        _prepare(fixture)
    assert _snapshot(controller, parent) == before
    assert automatic_bundle_preparation_status(controller.store, parent.id)["error_category"] == category


def test_explicit_retry_revalidates_inputs_before_new_attempt_or_model(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture

    def fail(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(runtime, "run", fail)
    with pytest.raises(AutomaticBundlePreparationError):
        _prepare(fixture)
    (parent.workspace / "data/raw/orders.csv").write_text("changed")
    before = _snapshot(controller, parent)
    with pytest.raises(EvolutionError):
        _prepare(fixture)
    assert _snapshot(controller, parent) == before
    status = automatic_bundle_preparation_status(controller.store, parent.id)
    assert status["error_category"] == "validation_error"
    assert status["recoverable"] is False


@pytest.mark.parametrize("write_kind", ["bundle_preparation_started", "bundle_preparation_failed"])
@pytest.mark.parametrize("failure_mode", ["raises", "false"])
def test_observation_write_failure_is_not_silently_suppressed(
    tmp_path, monkeypatch, write_kind, failure_mode,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    append = controller.store.append_event
    calls = []

    def fail_runtime(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()

    def write(run_id, kind, *args, **kwargs):
        if kind == write_kind:
            if failure_mode == "raises":
                raise RuntimeError("event ledger unavailable")
            return False
        return append(run_id, kind, *args, **kwargs)

    monkeypatch.setattr(runtime, "run", fail_runtime)
    monkeypatch.setattr(controller.store, "append_event", write)
    expected = RuntimeError if failure_mode == "raises" else EvolutionError
    with pytest.raises(expected) as caught:
        _prepare(fixture)
    assert not isinstance(caught.value, AutomaticBundlePreparationError)
    assert len(calls) == (0 if write_kind == "bundle_preparation_started" else 1)
    assert not _observations(controller, parent, "bundle_preparation_failed")


def test_old_runs_without_observations_and_prepared_runs_remain_compatible(tmp_path):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    assert automatic_bundle_preparation_status(controller.store, parent.id) is None
    _prepare(fixture)
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type LIKE 'bundle_preparation_%'", (parent.id,))
    before = _snapshot(controller, parent)
    assert automatic_bundle_preparation_status(controller.store, parent.id)["status"] == "prepared"
    _prepare(fixture)
    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_unprepared_terminal_parent_does_not_start_attempt(tmp_path, status):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, parent.id))
    with pytest.raises(EvolutionError):
        _prepare(fixture)
    assert not _observations(controller, parent)
    assert (runtime.bundle_calls, runtime.audit_calls) == (0, 0)


def _make_terminal(controller, parent, status):
    if status == "cancelled":
        assert controller.store.cancel_run(parent.id)
    elif status == "failed":
        assert controller.store.fail_budget(parent.id, "max_attempts", 2, 1, "fixture ceiling")
    else:
        with controller.store._connect() as connection:
            connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, parent.id))


@pytest.mark.parametrize("status", ["cancelled", "failed", "succeeded"])
@pytest.mark.parametrize("stage", ["compiler", "auditor"])
@pytest.mark.parametrize("runtime_fails", [False, True])
def test_terminal_parent_after_model_turn_stops_remaining_preparation(
    tmp_path, monkeypatch, status, stage, runtime_fails,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    run = runtime.run

    def complete(prompt, workspace, timeout=None):
        result = run(prompt, workspace, timeout)
        if ("adversarial evaluator auditor" in prompt) == (stage == "auditor"):
            _make_terminal(controller, parent, status)
            if runtime_fails:
                raise TimeoutError("private exception after terminal transition")
        return result

    monkeypatch.setattr(runtime, "run", complete)
    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    assert controller.store.get_run(parent.id).status.value == status
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 0 if stage == "compiler" else 1)
    assert caught.value.preparation["recoverable"] is False
    assert caught.value.preparation["error_category"] == (
        "cancelled" if status == "cancelled" else "validation_error"
    )
    assert not (parent.workspace / "evaluator-bundle").exists()
    assert not (parent.workspace / "bundle-profile.json").exists()
    assert not (parent.workspace / "evolution-run").exists()
    assert not any(event["type"] == "bundle_profile_prepared"
                   for event in controller.store.list_events(parent.id))
    assert len(_observations(controller, parent, "bundle_preparation_started")) == 1
    assert len(_observations(controller, parent, "bundle_preparation_failed")) == 1


@pytest.mark.parametrize("status", ["cancelled", "failed"])
@pytest.mark.parametrize("stage", ["before_profile", "after_profile", "before_marker"])
def test_terminal_parent_at_profile_publication_never_records_prepared(
    tmp_path, monkeypatch, status, stage,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    name = {"before_profile": "_profile_payload", "after_profile": "_write_profile",
            "before_marker": "_payload"}[stage]
    original = getattr(automatic_solve_bundle, name)

    def stop(*args, **kwargs):
        result = original(*args, **kwargs)
        _make_terminal(controller, parent, status)
        return result

    monkeypatch.setattr(automatic_solve_bundle, name, stop)
    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    assert controller.store.get_run(parent.id).status.value == status
    assert caught.value.preparation["recoverable"] is False
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert (parent.workspace / "evaluator-bundle").exists()
    assert not (parent.workspace / "evolution-run").exists()
    assert not any(event["type"] == "bundle_profile_prepared"
                   for event in controller.store.list_events(parent.id))
    if stage == "before_profile":
        assert not (parent.workspace / "bundle-profile.json").exists()


@pytest.mark.parametrize("status", ["cancelled", "failed"])
@pytest.mark.parametrize("stage", ["compiler", "audit"])
def test_terminal_parent_after_preflight_stops_audit_or_final_freeze(
    tmp_path, monkeypatch, status, stage,
):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    preflight = evaluator_bundle._preflight

    def stop(*args, **kwargs):
        result = preflight(*args, **kwargs)
        if kwargs.get("label") == stage:
            _make_terminal(controller, parent, status)
        return result

    monkeypatch.setattr(evaluator_bundle, "_preflight", stop)
    with pytest.raises(AutomaticBundlePreparationError) as caught:
        _prepare(fixture)

    assert controller.store.get_run(parent.id).status.value == status
    assert caught.value.preparation["recoverable"] is False
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 0 if stage == "compiler" else 1)
    assert not (parent.workspace / "evaluator-bundle").exists()
    assert not (parent.workspace / "bundle-profile.json").exists()


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_prepared_terminal_parent_keeps_readonly_recovery(tmp_path, status):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    _prepare(fixture)
    _make_terminal(controller, parent, status)
    before = _snapshot(controller, parent)

    _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
