"""Evidence scope is explicit and cannot silently weaken frozen evaluator coverage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE, BundleRuntime, _contract, _envelope
from test_snapshot_evaluator_bundle import SNAPSHOT_SOURCE

from famou import evaluator_bundle
from famou.algorithm import AlgorithmProblemContract, ConstraintSpec
from famou.conversational import ContractCompilationError, RuntimeContractCompiler, _parse_response
from famou.evaluator_bundle import (
    EvaluatorBundleError,
    UnsupportedEvaluatorConstraintsError,
    compile_evaluator_bundle,
    load_evaluator_bundle,
    validate_evaluator_capabilities,
)
from famou.evolution import CandidateInputArtifact


def scoped_contract(scope, *, group="hard_constraints", verification="partial"):
    payload = _contract().to_dict()
    constraint = payload["hard_constraints"][0]
    constraint["verification"] = verification
    constraint["result_fields"] = []
    if scope is not None:
        constraint["verification_scope"] = scope
    if group == "soft_constraints":
        payload["hard_constraints"] = []
        payload[group] = [constraint]
    return AlgorithmProblemContract.from_dict(payload)


def compile_fixture(runtime, root, contract, invocation):
    target = root / "data/raw/orders.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = b"id\nprivate-input-order\n"
    target.write_bytes(content)
    descriptor = CandidateInputArtifact("data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest())
    return compile_evaluator_bundle(
        runtime, contract, root, inputs=(descriptor,), timeout=2, invocation=invocation,
    )


@pytest.mark.parametrize("scope", ["output", "source", "execution"])
@pytest.mark.parametrize("group", ["hard_constraints", "soft_constraints"])
def test_scope_roundtrips_through_contract_intake_and_changes_digest(scope, group):
    original = scoped_contract(None, group=group)
    scoped = scoped_contract(scope, group=group)
    assert scoped.digest() != original.digest()
    assert scoped.to_dict()[group][0]["verification_scope"] == scope
    response = _parse_response(json.dumps({"status": "compiled", "contract": scoped.to_dict()}))
    assert response.contract == scoped
    assert AlgorithmProblemContract.from_dict(scoped.to_dict()).digest() == scoped.digest()
    constraint = getattr(scoped, group)[0]
    assert constraint.source == "user_confirmed"
    assert constraint.verification == "partial" and constraint.result_fields == ()


def test_legacy_serialization_and_frozen_digest_remain_identical():
    contract = _contract()
    assert contract.digest() == "4770a00b1c5433283381fa8c6bfcf60df511551892492f9082b63584455509a3"
    assert "verification_scope" not in contract.canonical_json()
    assert contract.hard_constraints[0].verification_scope is None
    assert _parse_response(json.dumps({"status": "compiled", "contract": contract.to_dict()})).contract == contract
    assert validate_evaluator_capabilities(contract) is None


@pytest.mark.parametrize("scope", [None, "", "OUTPUT", " output", "outputs", "input", True, 1, [], {}, ["output"]])
def test_explicit_invalid_scope_is_rejected_by_schema_and_intake(scope):
    payload = _contract().to_dict()
    constraint = payload["hard_constraints"][0]
    constraint["verification_scope"] = scope
    with pytest.raises((TypeError, ValueError), match="verification_scope"):
        ConstraintSpec.from_dict(constraint)
    with pytest.raises((TypeError, ValueError), match="verification_scope"):
        AlgorithmProblemContract.from_dict(payload)
    with pytest.raises(ContractCompilationError, match="verification_scope"):
        _parse_response(json.dumps({"status": "compiled", "contract": payload}))


@pytest.mark.parametrize("scope", ["", "unknown", True, 1, [], {}])
def test_invalid_scope_cannot_bypass_schema_through_direct_constraint_construction(scope):
    with pytest.raises(ValueError, match="verification_scope"):
        ConstraintSpec("requirement", "Constraint", "user_confirmed", "partial", verification_scope=scope)


def test_compiler_guidance_distinguishes_scope_strength_and_provenance():
    prompt = RuntimeContractCompiler._prompt("Deliver two Python files and read every input.", None)
    for scope in ("output", "source", "execution"):
        assert f'"{scope}"' in prompt
    assert "verification_scope" in prompt and "Declare the scope explicitly" in prompt
    assert "declared inputs and result files" in prompt
    assert "file count is source" in prompt and "reading every input is execution" in prompt
    assert "partial and empty result_fields do not remove a requirement" in prompt
    assert "request clarification" in prompt


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("group", ["hard_constraints", "soft_constraints"])
@pytest.mark.parametrize("scope", ["source", "execution"])
@pytest.mark.parametrize("verification", ["independent", "partial", "solver"])
def test_unsupported_scope_fails_before_model_workspace_or_frozen_load(
    tmp_path, monkeypatch, invocation, group, scope, verification,
):
    contract = scoped_contract(scope, group=group, verification=verification)
    runtime, root = BundleRuntime(), tmp_path / "must-remain-absent"

    def forbidden(*args, **kwargs):
        pytest.fail("unsupported scope reached filesystem or evaluator work")

    with monkeypatch.context() as patch:
        patch.setattr(evaluator_bundle, "_run_isolated", forbidden)
        patch.setattr(evaluator_bundle, "_build_input_profile", forbidden)
        patch.setattr(evaluator_bundle, "_snapshot_spec", forbidden)
        patch.setattr(Path, "is_symlink", forbidden)
        for action in (
            lambda: compile_evaluator_bundle(runtime, contract, root, invocation=invocation),
            lambda: load_evaluator_bundle(root, contract, invocation=invocation),
        ):
            with pytest.raises(UnsupportedEvaluatorConstraintsError) as caught:
                action()
            assert caught.value.unsupported_constraints == (("serve-all", scope),)
            assert caught.value.details() == [{"id": "serve-all", "verification_scope": scope}]
    assert not root.exists()
    assert (runtime.bundle_calls, runtime.audit_calls, runtime.generation_calls, runtime.evaluator_calls) == (0, 0, 0, 0)


def test_capability_error_reports_all_hard_and_soft_requirements_without_mutating_contract():
    payload = _contract().to_dict()
    output = {**payload["hard_constraints"][0], "verification_scope": "output"}
    source = {**output, "id": "two-files", "verification_scope": "source", "verification": "partial"}
    execution = {**output, "id": "all-inputs-used", "verification_scope": "execution", "verification": "solver"}
    payload["hard_constraints"] = [output, source]
    payload["soft_constraints"] = [execution]
    contract = AlgorithmProblemContract.from_dict(payload)
    before = contract.canonical_json()
    with pytest.raises(UnsupportedEvaluatorConstraintsError) as caught:
        validate_evaluator_capabilities(contract)
    assert caught.value.unsupported_constraints == (("two-files", "source"), ("all-inputs-used", "execution"))
    assert contract.canonical_json() == before


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("scope", [None, "output"])
def test_output_and_legacy_partial_constraints_compile_freeze_and_reload(tmp_path, invocation, scope):
    contract = scoped_contract(scope)
    source = EVALUATOR_SOURCE if invocation == "candidate" else SNAPSHOT_SOURCE
    runtime = BundleRuntime(_envelope(source))
    bundle = compile_fixture(runtime, tmp_path, contract, invocation)
    assert bundle.invocation == invocation
    assert runtime.bundle_calls == runtime.audit_calls == 1
    before = {path.name: path.read_bytes() for path in bundle.root.iterdir()}
    manifest = json.loads(before["manifest.json"])
    assert manifest["contract_sha256"] == contract.digest()
    assert load_evaluator_bundle(bundle.root, contract, invocation=invocation, timeout=2) == bundle
    assert compile_fixture(runtime, tmp_path, contract, invocation) == bundle
    assert runtime.bundle_calls == runtime.audit_calls == 1
    assert {path.name: path.read_bytes() for path in bundle.root.iterdir()} == before


@pytest.mark.parametrize("scope", [None, "output"])
@pytest.mark.parametrize("verification", ["partial", "solver"])
@pytest.mark.parametrize("omission", ["coverage", "invalid_probe"])
def test_partial_or_empty_fields_never_remove_required_hard_probe_coverage(
    tmp_path, scope, verification, omission,
):
    contract = scoped_contract(scope, verification=verification)
    envelope = _envelope()
    if omission == "coverage":
        envelope["constraint_coverage"] = []
    else:
        envelope["probes"] = [probe for probe in envelope["probes"] if probe["expected_validity"] == 1]
    runtime = BundleRuntime(envelope)
    with pytest.raises(EvaluatorBundleError, match="coverage must exactly match hard constraints"):
        compile_fixture(runtime, tmp_path, contract, "candidate")
    assert (runtime.bundle_calls, runtime.audit_calls, runtime.generation_calls) == (1, 0, 0)
    assert not (tmp_path / "evaluator-bundle").exists()
