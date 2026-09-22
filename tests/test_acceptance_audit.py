"""Offline adapter contracts; native validators are exercised in their own suites."""
from __future__ import annotations

import copy
import hashlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_audit_request import _request_payload

from lunar_evolution import acceptance_audit as module
from lunar_evolution._audit_request import build_acceptance_audit_request
from lunar_evolution.algorithm import OutputSpec
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import EvolutionError
from lunar_evolution.holdout_audit import build_holdout_declaration, build_holdout_receipt


def chain(request, count=6):
    pins = request["pins"]
    names = (("preparation", "profile"), ("generation", "bundle"), ("execution", "completion"),
             ("scoring", "evaluation"), ("selection", "selection"), ("delivery", "delivery"))
    return [{"schema_version": "1", "stage": stage, "receipt_id": "receipt-" + stage,
             "outcome": "succeeded", "manifest_sha256": request["manifest"]["manifest_sha256"],
             "preceding_stage_id": None if i == 0 else "receipt-" + names[i-1][0],
             "artifact_sha256": pins[pin + "_sha256"], "observed_ms": 1}
            for i, (stage, pin) in enumerate(names[:count])]


def native(request=None):
    request = request or build_acceptance_audit_request(_request_payload())
    result = module._NativeAudit(request, SimpleNamespace(), None, chain(request))
    result.parent = SimpleNamespace(id=result.ids["parent_run_id"], workspace=None)
    result.child = SimpleNamespace(id=result.ids["child_run_id"], workspace=None)
    return result


def test_public_api_is_exposed_and_cannot_receive_primary_override():
    import lunar_evolution as api
    assert api.audit_acceptance_artifacts is module.audit_acceptance_artifacts
    assert api.build_acceptance_audit_request is build_acceptance_audit_request
    with pytest.raises(TypeError, match="primary_eligible"):
        api.audit_acceptance_artifacts({}, primary_eligible=True)


@pytest.mark.parametrize("stage", ["preparation", "selection", "delivery"])
def test_native_errors_remain_path_free_reports(monkeypatch, stage):
    def fail(self):
        raise EvolutionError("private /workspace/provider-secret")
    monkeypatch.setattr(module._NativeAudit, stage, fail)
    report = native().capture(stage)
    assert report["status"] == "unverifiable"
    assert report["reason"] == stage + "_evidence_unverifiable"
    assert "private" not in str(report)


def test_successful_intake_validator_without_prepared_event_is_not_prepared(monkeypatch):
    audit = native()
    audit.contract = object()
    monkeypatch.setattr(module, "validate_automatic_solve_bundle", lambda *a: pytest.fail("missing event"))
    assert audit.capture("preparation")["reason"] == "prepared_receipt_missing"


def preparation(monkeypatch):
    audit = native()
    audit.contract = object()
    audit.parent.workspace = Path("/fixture/parent")
    inputs = [SimpleNamespace(to_dict=lambda: {
        "target": "input.txt", "source": "input", "size": 1, "sha256": "2" * 64,
    })]
    audit.manifest["input_sha256"] = hashlib.sha256(canonical_json([
        item.to_dict() for item in inputs
    ])).hexdigest()
    pipeline = SimpleNamespace(
        evaluator=SimpleNamespace(harness_sha256=audit.manifest["evaluator_sha256"]), inputs=inputs,
    )
    prepared = {"profile_sha256": audit.pins["profile_sha256"]}
    policy = {
        "automatic_lifecycle_version": 1, "bundle_mode": "compiled",
        "solve_wall_timeout": 3000, "solve_wall_timeout_source": "explicit",
        "timeout": 600, "evaluator_preparation_timeout": 900,
        "evaluator_preparation_wall_timeout": 1860,
    }
    audit.events = [
        {"run_id": audit.parent.id, "type": "bundle_profile_prepared", "payload": prepared},
        {"run_id": audit.parent.id, "type": "evolution_requested", "payload": policy},
    ]
    calls = []
    monkeypatch.setattr(module, "validate_automatic_solve_bundle", lambda *args: calls.append(("native", args)))
    monkeypatch.setattr(module, "load_bundle_pipeline", lambda path: calls.append(("profile", path)) or pipeline)
    return audit, policy, prepared, pipeline, calls


@pytest.mark.parametrize("numeric_type", [int, float])
def test_preparation_verifies_frozen_budgets_and_native_profile_bindings(monkeypatch, numeric_type):
    audit, policy, _, pipeline, calls = preparation(monkeypatch)
    for name in ("timeout", "evaluator_preparation_timeout", "evaluator_preparation_wall_timeout"):
        policy[name] = numeric_type(policy[name])
    report = audit.capture("preparation")
    assert report == {
        "boundary": "preparation", "status": "verified", "reason": None,
        "verified_digests": {
            "profile_sha256": audit.pins["profile_sha256"],
            "input_sha256": audit.manifest["input_sha256"],
            "evaluator_sha256": audit.manifest["evaluator_sha256"],
        },
    }
    assert audit.pipeline is pipeline
    assert calls == [("native", (audit.store, audit.parent.id)),
                     ("profile", audit.parent.workspace / "bundle-profile.json")]


@pytest.mark.parametrize("field", ["timeout", "evaluator_preparation_timeout", "evaluator_preparation_wall_timeout"])
def test_missing_preparation_budget_is_unverifiable(monkeypatch, field):
    audit, policy, _, _, calls = preparation(monkeypatch)
    del policy[field]
    report = audit.capture("preparation")
    assert report["status"] == "unverifiable"
    assert report["reason"] == "preparation_budget_missing"
    assert audit.pipeline is None and calls == []


@pytest.mark.parametrize("field", ["timeout", "evaluator_preparation_timeout", "evaluator_preparation_wall_timeout"])
@pytest.mark.parametrize("replacement", [1, 86400, 0, -1, True, False, None, "900", [], {}, float("nan"), float("inf")])
def test_mismatched_or_ill_typed_preparation_budget_fails(monkeypatch, field, replacement):
    audit, policy, _, _, calls = preparation(monkeypatch)
    policy[field] = replacement
    report = audit.capture("preparation")
    assert report["status"] == "failed"
    assert report["reason"] == "preparation_budget_mismatch"
    assert audit.pipeline is None and calls == []


@pytest.mark.parametrize("damage,reason", [
    ("profile", "profile_digest_mismatch"),
    ("evaluator", "evaluator_digest_mismatch"),
    ("inputs", "input_digest_mismatch"),
    ("receipt_count", "prepared_receipt_count"),
])
def test_preparation_requires_native_profile_evaluator_and_input_bindings(monkeypatch, damage, reason):
    audit, _, prepared, pipeline, _ = preparation(monkeypatch)
    if damage == "profile":
        prepared["profile_sha256"] = "f" * 64
    elif damage == "evaluator":
        pipeline.evaluator.harness_sha256 = "f" * 64
    elif damage == "inputs":
        pipeline.inputs = []
    else:
        audit.events.append(copy.deepcopy(audit.events[0]))
    report = audit.capture("preparation")
    assert report["status"] == "failed"
    assert report["reason"] == reason
    assert audit.pipeline is None


def test_native_preparation_rejection_cannot_publish_pipeline(monkeypatch):
    audit, _, _, _, calls = preparation(monkeypatch)

    def invalid(*args):
        raise EvolutionError("private /workspace/profile")

    monkeypatch.setattr(module, "validate_automatic_solve_bundle", invalid)
    report = audit.capture("preparation")
    assert report["status"] == "unverifiable"
    assert report["reason"] == "preparation_evidence_unverifiable"
    assert audit.pipeline is None and calls == []


def generation(audit, *, outcome="completed"):
    from lunar_evolution.candidate_generation_receipt import (
        build_candidate_generation_receipt,
        generation_event_id,
    )
    data = {
        "schema_version": "1", "stage": "candidate_generation", "outcome": outcome,
        "reason": outcome if outcome != "failed" else "worker_failed",
        "completion": outcome == "completed", "budget_id": audit.ids["generation_budget_id"],
        "max_tool_steps": 12, "tool_steps_used": 1, "tool_steps_remaining": 11,
        "attempted_tool_calls": 1,
    }
    if outcome == "completed":
        data.update(candidate_id=audit.ids["candidate_id"], source_bundle_sha256=audit.pins["bundle_sha256"])
    data = build_candidate_generation_receipt(
        data, run_id=audit.ids["child_run_id"], task_id=audit.ids["generation_task_id"],
    )
    return {"type": "agent_candidate_generation", "id": generation_event_id(data), "payload": data,
            "run_id": audit.ids["child_run_id"], "task_id": audit.ids["generation_task_id"]}


@pytest.mark.parametrize("damage", [None, "missing", "multiple", "owner", "candidate", "budget", "steps"])
def test_generation_requires_native_one_slot_receipt(damage):
    audit = native()
    audit.store.get_task = lambda _: SimpleNamespace(run_id=audit.ids["child_run_id"], orchestration=False)
    event = generation(audit)
    audit.events = [event]
    if damage == "missing":
        audit.events = []
    elif damage == "multiple":
        audit.events.append(copy.deepcopy(event))
    elif damage == "owner":
        event["task_id"] = "other"
    elif damage in {"candidate", "budget"}:
        event["payload"][damage + "_id"] = "other"
    elif damage == "steps":
        event["payload"].update(max_tool_steps=13, tool_steps_remaining=12)
    report = audit.capture("generation")
    assert (report["status"] == "verified") == (damage is None)


def scoring(audit):
    digest = lambda value: hashlib.sha256(canonical_json(value)).hexdigest()
    audit.contract = SimpleNamespace(outputs=(OutputSpec("output/result.txt", "text"),))
    audit.plan = SimpleNamespace(file_table_sha256="f" * 64)
    audit.record = SimpleNamespace(launch_intent_sha256="e" * 64)
    audit.child.workspace = Path("/fixture")
    audit.pipeline = SimpleNamespace(evaluator=SimpleNamespace(digest=lambda: "d" * 64, pin=lambda: "evaluator-pin"))
    audit.admission = SimpleNamespace(inputs=(), evaluator="evaluator-pin",
                                     output_contract_sha256=module.candidate_output_contract_sha256(audit.contract.outputs))
    audit.manifest["input_sha256"] = digest([])
    binding = {
        "workspace_plan_sha256": audit.pins["plan_sha256"], "admission_sha256": audit.pins["admission_sha256"],
        "bundle_sha256": audit.pins["bundle_sha256"], "contract_sha256": audit.pins["contract_sha256"],
        "evaluator_fingerprint": "d" * 64, "launch_intent_sha256": "e" * 64,
        "completion_sha256": audit.pins["completion_sha256"], "source_file_table_sha256": "f" * 64,
        "input_file_table_sha256": digest([]), "output_contract_sha256": audit.admission.output_contract_sha256,
    }
    value = {"binding": binding, "output_contract_valid": True, "harness_invoked": True}
    result = SimpleNamespace(to_dict=lambda: value, report=SimpleNamespace(validity=1),
                             digest=lambda: audit.pins["evaluation_sha256"])
    return value, result


@pytest.mark.parametrize("damage", [None, "invalid", "output", "harness", "input", "evaluator",
                                   "completion", "contract", "launch"])
def test_scoring_requires_validity_and_every_native_binding(monkeypatch, damage):
    audit = native()
    value, result = scoring(audit)
    calls = []
    def inspect(path, **kwargs):
        calls.append(kwargs)
        return result
    monkeypatch.setattr(module, "inspect_candidate_evaluation", inspect)
    if damage == "invalid":
        result.report.validity = 0
    elif damage in {"output", "harness"}:
        value["output_contract_valid" if damage == "output" else "harness_invoked"] = False
    elif damage == "input":
        value["binding"]["input_file_table_sha256"] = "a" * 64
    elif damage == "evaluator":
        audit.admission.evaluator = "other"
    elif damage in {"completion", "contract", "launch"}:
        key = "launch_intent_sha256" if damage == "launch" else damage + "_sha256"
        value["binding"][key] = "a" * 64
    report = audit.capture("scoring")
    assert (report["status"] == "verified") == (damage is None)
    assert calls == [{"expected_evaluation_sha256": audit.pins["evaluation_sha256"]}]


@pytest.mark.parametrize("damage", [None, "candidate", "selection", "evaluation", "missing", "multiple"])
def test_selection_must_match_native_choice_and_single_archived_candidate(monkeypatch, damage):
    audit = native()
    audit.evaluation = object()
    identity = {"candidate_id": audit.ids["candidate_id"], "contract_sha256": audit.pins["contract_sha256"],
                "bundle_sha256": audit.pins["bundle_sha256"], "receipt_sha256": audit.pins["selection_sha256"],
                "evaluation_sha256": audit.pins["evaluation_sha256"]}
    audit.events = [{"type": "evolution_candidate_archived", "run_id": audit.child.id,
                     "task_id": audit.ids["generation_task_id"], "payload": {"candidate_id": audit.ids["candidate_id"]}}]
    if damage == "candidate":
        identity["candidate_id"] = "other"
    elif damage in {"selection", "evaluation"}:
        identity["receipt_sha256" if damage == "selection" else "evaluation_sha256"] = "f" * 64
    elif damage == "missing":
        audit.events = []
    elif damage == "multiple":
        audit.events *= 2
    monkeypatch.setattr(module.LocalController, "_verified_bundle_evolution_delivery",
                        lambda *a: (identity, {}, None))
    report = audit.capture("selection")
    assert (report["status"] == "verified") == (damage is None)


@pytest.mark.parametrize("damage", [None, "failed", "invalid", "digest"])
def test_delivery_requires_native_success_and_pin(monkeypatch, damage):
    audit = native()
    audit.selected_identity = object()
    result = {"status": "succeeded", "validation": {"passed": True}, "delivery_sha256": audit.pins["delivery_sha256"]}
    if damage == "failed":
        result["status"] = "failed"
    elif damage == "invalid":
        result["validation"]["passed"] = False
    elif damage == "digest":
        result["delivery_sha256"] = "f" * 64
    monkeypatch.setattr(module, "inspect_bundle_parent_delivery", lambda *a: result)
    assert (audit.capture("delivery")["status"] == "verified") == (damage is None)


def test_combined_report_cannot_upgrade_unknown_execution_with_eight_holdouts(tmp_path, monkeypatch):
    payload = _request_payload()
    declaration = payload["holdout_declaration"]
    declaration.pop("declaration_sha256")
    snapshots = {}
    for h in declaration["holdouts"]:
        snapshots[h["holdout_id"]] = {"input": b"input", "expected_output": b"output", "actual_output": b"output"}
        h["input_sha256"] = hashlib.sha256(b"input").hexdigest()
        h["expected_output_sha256"] = hashlib.sha256(b"output").hexdigest()
    declaration = payload["holdout_declaration"] = build_holdout_declaration(declaration)
    request = build_acceptance_audit_request(payload)
    holdouts = []
    for h in declaration["holdouts"]:
        holdouts.append(build_holdout_receipt({
            **{k: v for k, v in declaration.items() if k != "holdouts"},
            **{k: v for k, v in h.items() if k != "max_duration_ms"},
            "actual_output_sha256": h["expected_output_sha256"], "native_exit_code": 0,
            "process_exit_code": 0, "cleanup": "verified", "duration_ms": 1, "outcome": "passed",
        }, declaration=declaration))
    root = tmp_path / request["manifest"]["campaign_root"]
    root.mkdir()
    @contextmanager
    def snapshot(_database):
        yield object()
    def capture(self, name):
        if name == "snapshot":
            self.parent = SimpleNamespace(workspace=root)
        return module._boundary(name, "unverifiable", "execution_cleanup_unknown") if name == "execution" else module._boundary(name)
    monkeypatch.setattr(module, "audit_snapshot", snapshot)
    monkeypatch.setattr(module._NativeAudit, "capture", capture)
    monkeypatch.setattr(module, "audit_parent_lifecycle", lambda *a, **kw: {"status": "verified", "reason": None})
    report = module.audit_acceptance_artifacts(
        request, database=tmp_path / "never-opened", audit_root=root, stage_receipts=chain(request),
        holdout_receipts=holdouts, retained_snapshots=snapshots,
    )
    assert report["first_problem"]["boundary"] == "execution"
    assert report["holdout_counts"] == {"passed": 8, "failed": 0, "unknown": 0, "missing": 0}
    assert report["primary_eligible"] is report["joint_eligible"] is False
    for name in ("primary_success", "joint_success", "preparation_success"):
        assert report[name] == "0/1"
    assert str(tmp_path) not in str(report)
