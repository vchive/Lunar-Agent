"""Failure-local budget evidence is partial, bounded, and never scoring authority."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from famou.agent_loop import AgentLoopRuntime, ProfileBudgetFailure
from famou.model_profile import BudgetFailureEvidence, UsageSnapshot
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.subject_diagnostics import (
    SubjectDiagnosticContext,
    SubjectDiagnosticObserver,
    normalize_diagnostic,
    publish_diagnostic,
)

CAP = 10**15
SECRET = "sk-diagnostic-secret-sentinel-123456789"


class Model:
    name = "fixture"
    api_key = SECRET

    def __init__(self, turns):
        self.turns = iter(turns)

    def complete(self, messages, tools=(), timeout=None):
        return next(self.turns)


def sample(total):
    return {"input_tokens": total - 1, "output_tokens": 1, "total_tokens": total}


def snapshot(total, rounds, *, priced=False):
    return {
        "input_tokens": total - rounds, "output_tokens": rounds, "total_tokens": total,
        "cost_micros": total if priced else None, "rounds": rounds,
    }


def context(root, *, deep=False):
    workspace = root / "attempt" / "subject"
    workspace.mkdir(parents=True)
    request = {
        "mode": "deep_evolution" if deep else "normal", "run_index": 1,
        "receipt_path": "receipts/002.json" if deep else "receipt.json",
        **({"round_index": 2} if deep else {}),
    }
    raw = json.dumps(request).encode()
    (workspace / "request.json").write_bytes(raw)
    return SubjectDiagnosticContext.from_request(workspace, request, hashlib.sha256(raw).hexdigest())


def claim(*, priced=False, exhausted=False):
    observed = snapshot(10 if exhausted else 11, 2, priced=priced)
    return {
        "limit": "max_cost_micros" if priced else "max_total_tokens",
        "state": "exhausted" if exhausted else "exceeded", "maximum": 10,
        "accepted_usage": observed.copy() if exhausted else snapshot(6, 1, priced=priced),
        "observed_usage": observed, "trigger_recorded": exhausted,
        "usage_completeness": "partial",
    }


def v2(ctx, budget=None):
    return {
        **ctx.payload("runtime", "budget_exceeded", 1, 1, None),
        "schema_version": "2", "budget": claim() if budget is None else budget,
    }


@pytest.mark.parametrize("priced", [False, True])
@pytest.mark.parametrize("exhausted", [False, True])
def test_real_loop_projects_trigger_separately_without_changing_event_counts(
    tmp_path: Path, priced: bool, exhausted: bool,
) -> None:
    ctx = context(tmp_path)
    observer = SubjectDiagnosticObserver()
    profile = ModelProfile("fixture", "fixture", **(
        {"max_cost_micros": 10, "input_cost_per_1k_micros": 1000, "output_cost_per_1k_micros": 1000}
        if priced else {"max_total_tokens": 10}
    ))
    model = Model([
        ModelTurn(SECRET, (ToolCall("first", "write_file", {"path": "kept", "content": SECRET}),),
                  usage=sample(6)),
        ModelTurn(SECRET, (ToolCall("second", "write_file", {"path": "forbidden", "content": SECRET}),),
                  response_model=SECRET, usage=sample(4 if exhausted else 5)),
    ])
    runtime = AgentLoopRuntime(model, profile=profile)
    runtime.set_event_sink(observer.event)
    with pytest.raises(RuntimeExecutionError, match="budget") as failure:
        runtime.run("solve", ctx.workspace)
    # Adapter wrappers preserve the typed evidence through the cause chain.
    wrapper = RuntimeError(SECRET)
    wrapper.__cause__ = failure.value
    payload = observer.failure(ctx, wrapper)
    assert payload == v2(ctx, claim(priced=priced, exhausted=exhausted))
    assert not (ctx.workspace / "forbidden").exists()
    assert (ctx.workspace / "kept").read_text() == SECRET
    ctx.emit(payload)
    encoded = (ctx.workspace / ctx.sidecar).read_bytes()
    assert len(encoded) <= 4096 and SECRET.encode() not in encoded
    assert normalize_diagnostic(json.loads(encoded)) == payload


@pytest.mark.parametrize("entrypoint", ["run", "run_isolated"])
def test_isolated_and_normal_first_rejection_have_zero_accepted_usage(tmp_path, entrypoint):
    ctx = context(tmp_path)
    runtime = AgentLoopRuntime(Model([ModelTurn(SECRET, usage=sample(11))]),
                               profile=ModelProfile("fixture", "fixture", max_total_tokens=10))
    with pytest.raises(RuntimeExecutionError) as failure:
        getattr(runtime, entrypoint)("solve", ctx.workspace)
    payload = SubjectDiagnosticObserver().failure(ctx, failure.value)
    expected = claim()
    expected["accepted_usage"] = snapshot(0, 0)
    expected["observed_usage"] = snapshot(11, 1)
    assert payload == {**v2(ctx, expected), "model_turns": 0, "tool_steps": 0}


@pytest.mark.parametrize("usage", [None, {"total_tokens": 11},
                                  {"input_tokens": True, "output_tokens": 10, "total_tokens": 11}])
def test_missing_and_invalid_usage_never_create_budget_evidence(tmp_path, usage):
    ctx = context(tmp_path)
    runtime = AgentLoopRuntime(Model([ModelTurn(SECRET, usage=usage)]),
                               profile=ModelProfile("fixture", "fixture", max_total_tokens=10))
    with pytest.raises(RuntimeExecutionError) as failure:
        runtime.run("solve", ctx.workspace)
    payload = SubjectDiagnosticObserver().failure(ctx, failure.value)
    assert payload["schema_version"] == "1"
    assert payload["code"] == "usage_invalid" and "budget" not in payload
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("maximum", [10, CAP + 1])
def test_unrepresentable_numbers_become_null_without_changing_execution(tmp_path, maximum):
    ctx = context(tmp_path)
    runtime = AgentLoopRuntime(Model([ModelTurn(SECRET, usage=sample(CAP + 2))]),
                               profile=ModelProfile("fixture", "fixture", max_total_tokens=maximum))
    with pytest.raises(RuntimeExecutionError, match="budget exceeded") as failure:
        runtime.run("solve", ctx.workspace)
    payload = SubjectDiagnosticObserver().failure(ctx, failure.value)
    assert payload["schema_version"] == "2"
    budget = payload["budget"]
    assert budget["maximum"] == (maximum if maximum <= CAP else None)
    assert budget["observed_usage"] is None
    assert budget["accepted_usage"] == snapshot(0, 0)
    assert budget["usage_completeness"] == "partial"
    assert normalize_diagnostic(payload) == payload


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("version", ["1", "2"])
def test_versions_collect_without_upgrading_or_mutating_claims(tmp_path, deep, version):
    ctx = context(tmp_path, deep=deep)
    payload = v2(ctx) if version == "2" else ctx.payload("runtime", "budget_exceeded", 1, 1, None)
    original = deepcopy(payload)
    publish_diagnostic(ctx.workspace, ctx.sidecar, payload)
    ctx.collect()
    name = "subject-002-failure.json" if deep else "subject-failure.json"
    collected = json.loads((ctx.workspace.parent / "diagnostics" / name).read_text())
    assert collected == original == payload
    assert (ctx.workspace / ctx.sidecar).read_bytes() == (ctx.workspace.parent / "diagnostics" / name).read_bytes()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "3"), (("stage",), "model"), (("code",), "timeout"),
    (("http_status",), 429), (("score",), 1), (("budget", "extra"), SECRET),
    (("budget", "limit"), SECRET), (("budget", "state"), "finished"),
    (("budget", "maximum"), True), (("budget", "maximum"), -1),
    (("budget", "maximum"), 0), (("budget", "maximum"), 10.0),
    (("budget", "maximum"), CAP + 1), (("budget", "maximum"), 11),
    (("budget", "trigger_recorded"), True), (("budget", "trigger_recorded"), 0),
    (("budget", "usage_completeness"), "complete"),
    (("budget", "observed_usage", "total_tokens"), 12),
    (("budget", "observed_usage", "output_tokens"), False),
    (("budget", "observed_usage", "cost_micros"), SECRET),
    (("budget", "observed_usage", "cost_micros"), CAP + 1),
    (("budget", "observed_usage", "input_tokens"), CAP + 1),
    (("budget", "observed_usage", "rounds"), 0),
    (("budget", "observed_usage", "rounds"), 1),
    (("budget", "accepted_usage", "rounds"), 0),
    (("budget", "accepted_usage", "rounds"), 1_000_001),
    (("budget", "observed_usage", "extra"), SECRET),
])
def test_malformed_v2_is_rejected_and_never_collected(tmp_path, path, value):
    ctx = context(tmp_path)
    payload = v2(ctx)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)
    (ctx.workspace / ctx.sidecar).write_text(json.dumps(payload))
    ctx.collect()
    assert not (ctx.workspace.parent / "diagnostics").exists()


@pytest.mark.parametrize("change", ["v1-budget", "v2-missing", "cost-null", "nonmonotone", "unequal"])
def test_inconsistent_budget_contracts_are_rejected(tmp_path, change):
    ctx = context(tmp_path)
    payload = v2(ctx)
    if change == "v1-budget":
        payload["schema_version"] = "1"
    elif change == "v2-missing":
        del payload["budget"]
    elif change == "cost-null":
        payload["budget"]["limit"] = "max_cost_micros"
    elif change == "nonmonotone":
        payload["budget"]["accepted_usage"] = {
            "input_tokens": 1, "output_tokens": 5, "total_tokens": 6, "cost_micros": None, "rounds": 1,
        }
    else:
        payload["budget"] = claim(exhausted=True)
        payload["budget"]["accepted_usage"] = snapshot(6, 1)
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


def test_exception_prose_and_arbitrary_attributes_cannot_supply_numeric_evidence(tmp_path):
    ctx = context(tmp_path)
    error = RuntimeExecutionError("model profile budget exceeded: max_total_tokens")
    error.evidence = claim()
    payload = SubjectDiagnosticObserver().failure(ctx, error)
    assert payload["schema_version"] == "1" and "budget" not in payload
    assert payload["code"] == "budget_exceeded"


def test_model_failure_cannot_masquerade_as_runtime_budget_failure(tmp_path):
    ctx = context(tmp_path)
    runtime = AgentLoopRuntime(Model([ModelTurn(SECRET, usage=sample(11))]),
                               profile=ModelProfile("fixture", "fixture", max_total_tokens=10))
    with pytest.raises(RuntimeExecutionError) as failure:
        runtime.run("solve", ctx.workspace)
    observer = SubjectDiagnosticObserver()
    observer.event("agent_runtime_failure", {"phase": "model_turn"})
    payload = observer.failure(ctx, failure.value)
    assert payload["schema_version"] == "1" and "budget" not in payload
    assert payload["stage"] == "model" and payload["code"] == "model_failed"


def test_large_exhausted_ledger_is_unknown_without_clamping_or_losing_classification(tmp_path):
    ctx = context(tmp_path)
    runtime = AgentLoopRuntime(Model([
        ModelTurn(SECRET, (ToolCall("write", "write_file", {"path": "forbidden", "content": SECRET}),),
                  usage=sample(CAP + 1)),
    ]), profile=ModelProfile("fixture", "fixture", max_total_tokens=CAP + 1))
    with pytest.raises(RuntimeExecutionError, match="budget exhausted") as failure:
        runtime.run("solve", ctx.workspace)
    payload = SubjectDiagnosticObserver().failure(ctx, failure.value)
    assert payload["budget"] == {
        "limit": "max_total_tokens", "state": "exhausted", "maximum": None,
        "accepted_usage": None, "observed_usage": None,
        "trigger_recorded": True, "usage_completeness": "partial",
    }
    assert normalize_diagnostic(payload) == payload
    assert not (ctx.workspace / "forbidden").exists()


@pytest.mark.parametrize("field,value", [("limit", SECRET), ("maximum", True),
                                         ("observed_usage", {"secret": SECRET})])
def test_invalid_typed_evidence_falls_back_to_safe_v1_classification(tmp_path, field, value):
    ctx = context(tmp_path)
    evidence = BudgetFailureEvidence(
        limit="max_total_tokens", state="exceeded", maximum=10,
        accepted_usage=UsageSnapshot(0, 0, 0, None, 0),
        observed_usage=UsageSnapshot(10, 1, 11, None, 1), trigger_recorded=False,
    )
    error = ProfileBudgetFailure(replace(evidence, **{field: value}))
    SubjectDiagnosticObserver().emit_failure(ctx, error)
    payload = json.loads((ctx.workspace / ctx.sidecar).read_text())
    assert payload == ctx.payload("runtime", "budget_exceeded", 0, 0, None)
    assert SECRET not in json.dumps(payload)
