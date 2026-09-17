"""Bounded local diagnostics are optional observations, never a success criterion."""
from __future__ import annotations

import copy
import json

import pytest
import test_measurement128_runner as runner
from test_measurement128_runner import load, start_worker

from famou.evaluator_bundle import EvaluatorBundleError, EvaluatorPreparationError
from famou.evaluator_diagnostics import EvaluatorPreparationDiagnostic

modules = runner.modules


@pytest.fixture
def worker(modules, monkeypatch):
    return load(monkeypatch, "measurement128_diagnostic_worker", "worker.py")


@pytest.fixture
def analysis(modules, monkeypatch):
    return load(monkeypatch, "measurement128_diagnostic_analysis", "analysis.py")


def diagnostic(stage="compiler_preflight", reason="input_format_invalid", **changes):
    value = {"schema_version": "1", "stage": stage, "reason": reason,
             "probe_index": 1, "input_index": 1, "order_index": None}
    value.update(changes)
    return value


def error(value=None):
    return EvaluatorPreparationError(
        "private exception text and generated identifiers",
        EvaluatorPreparationDiagnostic.from_dict(diagnostic() if value is None else value),
    )


def usage(count=1):
    return {"provider_requests": count, "finished_requests": count,
            "pending_requests": [], "requests": [
                {"index": index, "stage": "evaluator_compiler" if index == 1 else "evaluator_auditor",
                 "outcome": "succeeded"} for index in range(1, count + 1)]}


def result(value=None):
    return {"status": "failed", "stage": "preparation", "frozen": None,
            "error_class": "EvaluatorPreparationError", "local_failure": value or diagnostic()}


@pytest.mark.parametrize("value", [
    diagnostic(),
    diagnostic("auditor_preflight"),
    diagnostic("compiler_response", "response_invalid", probe_index=None, input_index=None),
    diagnostic("auditor_response", "response_invalid", probe_index=None, input_index=None),
    diagnostic("auditor_preflight", "report_invalid", probe_index=64, input_index=None),
    diagnostic("auditor_preflight", "validity_mismatch", probe_index=2, input_index=None),
    diagnostic("compiler_preflight", "score_order_mismatch", probe_index=None, input_index=None, order_index=64),
    diagnostic("compiler_preflight", "preflight_failed", probe_index=None, input_index=None),
])
def test_worker_projects_only_native_valid_six_key_diagnostic(worker, value):
    exc = error(value)
    exc.generated_source = "private generated source"
    projection = worker.local_failure_detail(exc, stage="preparation", frozen=None)
    assert projection == value
    assert projection is not value
    assert set(projection) == {"schema_version", "stage", "reason", "probe_index", "input_index", "order_index"}
    assert "private" not in json.dumps(projection)
    projection["reason"] = "changed"
    assert worker.local_failure_detail(exc, stage="preparation", frozen=None) == value


@pytest.mark.parametrize("stage,frozen", [
    ("setup", None), ("holdouts", None), ("finished", None), (None, None),
    ("preparation", {}), ("preparation", {"fingerprint": "a" * 64}),
])
def test_worker_never_claims_preparation_observation_outside_unfrozen_preparation(worker, stage, frozen):
    assert worker.local_failure_detail(error(), stage=stage, frozen=frozen) is None


def test_worker_ignores_arbitrary_exceptions_and_subclass_hooks(worker):
    class CustomError(EvaluatorPreparationError):
        @property
        def diagnostic(self):
            pytest.fail("subclass diagnostic property was evaluated")

    plain = EvaluatorBundleError("private")
    plain.diagnostic = EvaluatorPreparationDiagnostic.from_dict(diagnostic())
    arbitrary = ValueError("private")
    arbitrary.diagnostic = diagnostic()
    subclass = CustomError.__new__(CustomError)
    for exc in (plain, arbitrary, subclass, Exception("private")):
        assert worker.local_failure_detail(exc, stage="preparation", frozen=None) is None


@pytest.mark.parametrize("replacement", [None, {}, diagnostic(), "private typed object"])
def test_worker_ignores_replaced_typed_diagnostic(worker, replacement):
    exc = error()
    exc.diagnostic = replacement
    assert worker.local_failure_detail(exc, stage="preparation", frozen=None) is None


@pytest.mark.parametrize("field,value", [
    ("stage", "private-stage"), ("reason", "private-reason"),
    ("probe_index", True), ("probe_index", 0), ("probe_index", 65),
    ("input_index", 0), ("input_index", 33), ("input_index", 1.0),
    ("order_index", 1),
])
def test_worker_revalidates_mutated_native_diagnostic_without_raising(worker, field, value):
    exc = error()
    object.__setattr__(exc.diagnostic, field, value)
    assert worker.local_failure_detail(exc, stage="preparation", frozen=None) is None


def test_worker_rejects_diagnostic_subclass_without_invoking_projection(worker):
    class CustomDiagnostic(EvaluatorPreparationDiagnostic):
        def to_dict(self):
            pytest.fail("diagnostic subclass projection executed")

    exc = error()
    exc.diagnostic = CustomDiagnostic("compiler_preflight", "input_format_invalid", 1, 1)
    assert worker.local_failure_detail(exc, stage="preparation", frozen=None) is None


def test_worker_preserves_failure_when_observational_projection_cannot_publish(
    worker, modules, monkeypatch,
):
    campaign, _, _, _, manifest, provider = modules
    _, slot = start_worker(campaign, manifest)
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)
    monkeypatch.setattr(worker, "load_provider", lambda **kwargs: provider)
    exc = error()
    object.__setattr__(exc.diagnostic, "reason", "private malformed diagnostic")

    def reject(*args, **kwargs):
        raise exc

    def forbidden(*args, **kwargs):
        pytest.fail("local failure handling attempted a model request or holdout")

    monkeypatch.setattr(worker, "compile_evaluator_bundle", reject)
    monkeypatch.setattr(worker, "audit_holdouts", forbidden)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.OpenAICompatibleRuntime.complete", forbidden)
    assert worker.main() == 1
    recorded = json.loads((slot / "worker-finished.json").read_text())
    assert recorded["status"] == "failed" and recorded["stage"] == "preparation"
    assert recorded["error_class"] == "EvaluatorPreparationError"
    assert recorded.get("local_failure") is None
    assert recorded["frozen"] is None and recorded["holdouts"] == []
    assert recorded["guard"]["provider_requests"] == 0
    assert "private" not in json.dumps(recorded)


@pytest.mark.parametrize("stage", [
    "compiler_preflight", "compiler_response", "auditor_preflight", "auditor_response",
])
def test_analysis_accepts_typed_detail_only_with_matching_completed_requests(analysis, stage):
    value = diagnostic(stage)
    if stage.endswith("response"):
        value.update(reason="response_invalid", probe_index=None, input_index=None)
    count = 1 if stage.startswith("compiler") else 2
    original = result(value)
    before = copy.deepcopy(original)
    assert analysis.local_failure_summary(original, usage=usage(count), frozen=None) == value
    assert original == before


@pytest.mark.parametrize("worker_value", [None, {}, {"local_failure": None}, {"status": "failed"}])
def test_analysis_missing_observation_stays_nullable(analysis, worker_value):
    assert analysis.local_failure_summary(worker_value, usage=usage(), frozen=None) is None


@pytest.mark.parametrize("change", [
    {"schema_version": "2"}, {"schema_version": 1}, {"stage": "private-stage"},
    {"reason": "private-reason"}, {"probe_index": True}, {"probe_index": 65},
    {"probe_index": 0}, {"input_index": 33}, {"input_index": 0}, {"order_index": 1},
    {"extra": "private"}, {"probe_index": 1.0}, {"input_index": "1"},
])
def test_analysis_rejects_malformed_native_diagnostic(analysis, change):
    value = diagnostic()
    value.update(change)
    with pytest.raises(ValueError):
        analysis.local_failure_summary(result(value), usage=usage(), frozen=None)


@pytest.mark.parametrize("missing", ["schema_version", "stage", "reason", "probe_index", "input_index", "order_index"])
def test_analysis_requires_all_six_diagnostic_keys(analysis, missing):
    value = diagnostic()
    del value[missing]
    with pytest.raises(ValueError):
        analysis.local_failure_summary(result(value), usage=usage(), frozen=None)


@pytest.mark.parametrize("value", ["private-text", [], True, 1])
def test_analysis_rejects_non_object_observation(analysis, value):
    recorded = result()
    recorded["local_failure"] = value
    with pytest.raises(ValueError):
        analysis.local_failure_summary(recorded, usage=usage(), frozen=None)


@pytest.mark.parametrize("change,frozen", [
    ({"status": "completed"}, None), ({"status": None}, None),
    ({"stage": "setup"}, None), ({"stage": "holdouts"}, None),
    ({"stage": "finished"}, None), ({"error_class": "ValueError"}, None),
    ({"error_class": None}, None), ({"frozen": {}}, None),
    ({}, {}), ({}, {"fingerprint": "a" * 64}),
])
def test_analysis_rejects_observation_incompatible_with_worker_or_freeze(analysis, change, frozen):
    recorded = result()
    recorded.update(change)
    with pytest.raises(ValueError):
        analysis.local_failure_summary(recorded, usage=usage(), frozen=frozen)


@pytest.mark.parametrize("stage,count", [
    ("compiler_preflight", 0), ("compiler_preflight", 2),
    ("auditor_preflight", 0), ("auditor_preflight", 1),
])
def test_analysis_rejects_request_count_inconsistent_with_local_stage(analysis, stage, count):
    with pytest.raises(ValueError):
        analysis.local_failure_summary(result(diagnostic(stage)), usage=usage(count), frozen=None)


@pytest.mark.parametrize("stage", ["compiler_preflight", "auditor_preflight"])
@pytest.mark.parametrize("corruption", [
    "unfinished", "pending", "failed_compiler", "missing_row", "duplicate_row", "wrong_index", "wrong_stage",
])
def test_analysis_requires_ordered_successful_complete_requests(analysis, stage, corruption):
    observed = usage(1 if stage.startswith("compiler") else 2)
    if corruption == "unfinished":
        observed["finished_requests"] -= 1
    elif corruption == "pending":
        observed["pending_requests"] = [1]
    elif corruption == "failed_compiler":
        observed["requests"][0]["outcome"] = "provider_error"
    elif corruption == "missing_row":
        observed["requests"].pop()
    elif corruption == "duplicate_row":
        observed["requests"].append(copy.deepcopy(observed["requests"][0]))
    elif corruption == "wrong_index":
        observed["requests"][0]["index"] = 2
    elif corruption == "wrong_stage":
        observed["requests"][0]["stage"] = "evaluator_auditor"
    with pytest.raises(ValueError):
        analysis.local_failure_summary(result(diagnostic(stage)), usage=observed, frozen=None)


def test_analysis_requires_auditor_request_succeeded(analysis):
    observed = usage(2)
    observed["requests"][1]["outcome"] = "invalid_turn"
    with pytest.raises(ValueError):
        analysis.local_failure_summary(result(diagnostic("auditor_preflight")), usage=observed, frozen=None)
