"""Static execution declarations bind every identity before any optional input read."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from famou import _benchmark_files as files
from famou.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from famou.candidate_execution import (
    MAX_EXECUTION_ADMISSION_BYTES,
    MAX_EXECUTION_INPUT_BYTES,
    MAX_EXECUTION_OUTPUT_BYTES,
    MAX_EXECUTION_PROCESSES,
    MAX_EXECUTION_TIMEOUT_SECONDS,
    CandidateEvaluatorPin,
    CandidateExecutionAdmission,
    CandidateExecutionBudget,
    CandidateExecutionError,
    CandidateExecutionInput,
    VerifiedCandidateExecutionAdmission,
    admit_candidate_execution,
    build_candidate_execution_admission,
    parse_candidate_execution_admission,
    validate_candidate_execution_admission,
)
from famou.candidate_workspace_plan import build_candidate_workspace_plan

CONTRACT = "a" * 64
DEPENDENCY = "b" * 64
ENVIRONMENT = "c" * 64
EVALUATOR = "d" * 64
OUTPUT = "e" * 64


def _plan(**kwargs):
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT, "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })
    return build_candidate_workspace_plan(
        bundle, contract_sha256=CONTRACT, command=["/nonexistent/runner", "main.py"],
        timeout_seconds=5, max_output_bytes=1024, **kwargs,
    )


def _input(target="input.txt", content=b"fixture"):
    return CandidateExecutionInput(target, "fixture", len(content), hashlib.sha256(content).hexdigest())


def _admission(inputs=(), **kwargs):
    fields = {
        "inputs": inputs, "dependency_sha256": DEPENDENCY,
        "environment_sha256": ENVIRONMENT,
        "evaluator": CandidateEvaluatorPin("exact-harness", EVALUATOR),
        "output_contract_sha256": OUTPUT, "budget": CandidateExecutionBudget(5, 1024, 1024, 1),
    }
    fields.update(kwargs)
    return build_candidate_execution_admission(_plan(), **fields)


def test_canonical_result_roundtrips_and_excludes_its_self_digest():
    admission = _admission([_input("z"), _input("a")])
    payload = admission.to_dict(include_admission_sha256=False)
    assert set(payload) == {
        "schema_version", "protocol", "workspace_plan_sha256", "bundle_sha256",
        "contract_sha256", "inputs", "dependency_sha256", "environment_sha256",
        "evaluator", "output_contract_sha256", "budget",
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert admission.digest() == hashlib.sha256(canonical.encode()).hexdigest()
    assert admission.to_dict()["admission_sha256"] == admission.digest()
    assert admission.digest() == _admission(list(reversed(admission.inputs))).digest()
    assert parse_candidate_execution_admission(payload) == admission
    assert parse_candidate_execution_admission(json.dumps(admission.to_dict())) == admission
    assert parse_candidate_execution_admission(json.dumps(admission.to_dict()).encode()) == admission
    assert validate_candidate_execution_admission(admission) == admission


def test_complete_plan_environment_command_and_limits_affect_identity():
    first = _plan(environment={"Z": "private", "A": "explicit"})
    second = _plan(environment={"A": "explicit", "Z": "private"})
    inputs = {
        "inputs": (), "dependency_sha256": DEPENDENCY, "environment_sha256": ENVIRONMENT,
        "evaluator": CandidateEvaluatorPin("exact", EVALUATOR), "output_contract_sha256": OUTPUT,
        "budget": CandidateExecutionBudget(10, 2048, 1, 1),
    }
    admission = build_candidate_execution_admission(first, **inputs)
    assert admission.digest() == build_candidate_execution_admission(second, **inputs).digest()
    for plan in [
        replace(first, command=("/another/runner", "main.py")),
        replace(first, timeout_seconds=6),
        replace(first, max_output_bytes=2048),
        replace(first, environment=(("A", "changed"),)),
    ]:
        assert admission.digest() != build_candidate_execution_admission(plan, **inputs).digest()
    serialized = json.dumps(admission.to_dict())
    assert "/nonexistent" not in serialized
    assert "private" not in serialized
    assert "explicit" not in serialized


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(dependency_sha256="f" * 64),
    lambda p: p.update(environment_sha256="f" * 64),
    lambda p: p.update(output_contract_sha256="f" * 64),
    lambda p: p["evaluator"].update(kind="another-harness"),
    lambda p: p["evaluator"].update(fingerprint="f" * 64),
    lambda p: p["inputs"][0].update(source_label="another-source"),
    lambda p: p["inputs"][0].update(target="another.txt"),
    lambda p: p["inputs"][0].update(sha256="f" * 64),
    lambda p: p["inputs"][0].update(size=0),
    lambda p: p["budget"].update(timeout_seconds=6),
    lambda p: p["budget"].update(max_output_bytes=2048),
    lambda p: p["budget"].update(max_input_bytes=2048),
    lambda p: p["budget"].update(max_processes=2),
])
def test_every_bound_field_changes_digest(mutate):
    admission = _admission([_input()])
    payload = admission.to_dict(include_admission_sha256=False)
    mutate(payload)
    assert parse_candidate_execution_admission(payload).digest() != admission.digest()


def test_all_structural_paths_are_pure_memory(monkeypatch):
    plan = _plan()
    admission = _admission()
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("filesystem opened"))
    monkeypatch.setattr(Path, "stat", lambda *_a, **_kw: pytest.fail("filesystem stat"))
    monkeypatch.setattr(files, "read_regular_file", lambda *_a, **_kw: pytest.fail("input read"))
    assert parse_candidate_execution_admission(json.dumps(admission.to_dict())).digest() == admission.digest()
    assert validate_candidate_execution_admission(admission) == admission
    result = admit_candidate_execution(admission, plan=plan)
    assert result.observed_inputs is None
    assert result.inputs_verified is False
    for value in ["/host/private/admission.json", Path("/host/private/admission.json")]:
        with pytest.raises(CandidateExecutionError, match="^candidate_execution_invalid$"):
            parse_candidate_execution_admission(value)


@pytest.mark.parametrize("content", [
    b'{"inputs":[],"inputs":[]}', b'{"budget":{"max_processes":1,"max_processes":2}}',
    b'{"budget":NaN}', b'{"budget":Infinity}', b"{}", b"[]", b"null", b"", b"\xff",
    b"[" * 2000 + b"]" * 2000,
])
def test_parser_rejects_non_strict_json(content):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_invalid$"):
        parse_candidate_execution_admission(content)


def test_parser_bounds_raw_json_before_decode():
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_too_large$"):
        parse_candidate_execution_admission(b" " * (MAX_EXECUTION_ADMISSION_BYTES + 1))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_too_large$"):
        parse_candidate_execution_admission("é" * MAX_EXECUTION_ADMISSION_BYTES)


def test_admission_reserves_returned_self_digest_space_at_the_envelope_limit():
    payload = _admission().to_dict(include_admission_sha256=False)
    payload["inputs"] = [
        {"target": f'{index:02}-' + '"' * 829, "source_label": "f" * 256, "size": 0, "sha256": "a" * 64}
        for index in range(64)
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert len(canonical) < MAX_EXECUTION_ADMISSION_BYTES
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_too_large$"):
        parse_candidate_execution_admission(payload)
    for item in payload["inputs"]:
        item["target"] = item["target"][:-1]
    admission = parse_candidate_execution_admission(payload)
    returned = json.dumps(admission.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert len(returned) <= MAX_EXECUTION_ADMISSION_BYTES
    assert parse_candidate_execution_admission(returned).digest() == admission.digest()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(schema_version=1),
    lambda p: p.update(protocol="unknown"),
    lambda p: p.update(unknown=True),
    lambda p: p.pop("budget"),
    lambda p: p.update(admission_sha256="f" * 64),
    lambda p: p.update(admission_sha256=None),
    lambda p: p.update(inputs=[{}] * 65),
    lambda p: p.update(inputs={}),
    lambda p: p["inputs"][0].update(extra="private-value"),
])
def test_strict_schema_rejects_invalid_declarations(mutate):
    payload = _admission([_input()]).to_dict()
    mutate(payload)
    with pytest.raises(CandidateExecutionError):
        parse_candidate_execution_admission(payload)


@pytest.mark.parametrize("target", [
    "", ".", "./", "/tmp/x", "../x", "a/../x", "a//x", "a\\x", "a/./x", "a/",
    ".git/config", "a/.GIT/config", "C:input", "e\u0301.txt", "a\x00b", "a\u200bb",
    "\ud800", "é" * 513, None, [],
])
def test_input_target_is_canonical_and_relative(target):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_(?:invalid|unsafe)$"):
        CandidateExecutionInput(target, "fixture", 0, hashlib.sha256(b"").hexdigest())


@pytest.mark.parametrize("targets", [
    ("a", "a"), ("A", "a"), ("a", "a/b"), ("A/x", "a/y"), ("Straße/x", "STRASSE/y"),
])
def test_duplicate_files_ancestor_collisions_and_case_aliases(targets):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_unsafe$"):
        _admission([_input(target) for target in targets])


@pytest.mark.parametrize("label", [
    "", "/machine/path", "C:input", "a\\b", "a b", "sk-abcdefghijk", "token=abc",
    "a\x00b", "a\u200bb", "a" * 257, None,
])
def test_source_labels_are_opaque_bounded_identifiers(label):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_invalid$"):
        CandidateExecutionInput("input", label, 0, hashlib.sha256(b"").hexdigest())


@pytest.mark.parametrize("kind", [
    "", "https://host", "token=abc", "sk-abcdefghijk", "$(id)", "`id`", "x;id", "x|id",
    "x y", "x\t", "x\u200b", "0.95", "x" * 129, None,
])
def test_evaluator_kind_cannot_carry_prose_shell_syntax_or_score(kind):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_evaluator_mismatch$"):
        CandidateEvaluatorPin(kind, EVALUATOR)


@pytest.mark.parametrize("field", ["dependency_sha256", "environment_sha256"])
@pytest.mark.parametrize("value", ["0" * 64, "A" * 64, "", None, True])
def test_commitments_are_real_lowercase_digests(field, value):
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{field.removesuffix('_sha256')}_mismatch$"):
        _admission(**{field: value})


@pytest.mark.parametrize("field", ["timeout_seconds", "max_output_bytes", "max_input_bytes", "max_processes"])
@pytest.mark.parametrize("value", [True, None, "1", 0, -1, float("nan"), float("inf")])
def test_budget_rejects_invalid_values(field, value):
    fields = {"timeout_seconds": 1, "max_output_bytes": 1, "max_input_bytes": 1, "max_processes": 1}
    fields[field] = value
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
        CandidateExecutionBudget(**fields)


def test_budget_accepts_exact_limits_and_rejects_overflow_and_sum():
    budget = CandidateExecutionBudget(
        MAX_EXECUTION_TIMEOUT_SECONDS, MAX_EXECUTION_OUTPUT_BYTES,
        MAX_EXECUTION_INPUT_BYTES, MAX_EXECUTION_PROCESSES,
    )
    assert budget.timeout_seconds == float(MAX_EXECUTION_TIMEOUT_SECONDS)
    for field in ["timeout_seconds", "max_output_bytes", "max_input_bytes", "max_processes"]:
        payload = budget.to_dict()
        payload[field] += 1
        with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
            CandidateExecutionBudget.from_dict(payload)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
        CandidateExecutionBudget(10**10000, 1, 1, 1)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
        _admission([_input(content=b"large")], budget=CandidateExecutionBudget(5, 1024, 1, 1))


def test_source_only_is_the_only_output_contract_omission():
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_output_contract_mismatch$"):
        _admission(output_contract_sha256=None)
    admission = _admission(evaluator=CandidateEvaluatorPin("source-only", EVALUATOR), output_contract_sha256=None)
    assert admission.output_contract_sha256 is None
    assert admit_candidate_execution(admission, plan=_plan(), expected_output_contract_sha256=None).admission == admission
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_output_contract_mismatch$"):
        admit_candidate_execution(_admission(), plan=_plan(), expected_output_contract_sha256=None)


def test_constructor_detaches_every_nested_caller_value():
    item = _input()
    evaluator = CandidateEvaluatorPin("exact", EVALUATOR)
    budget = CandidateExecutionBudget(5, 1024, 1024, 1)
    inputs = [item]
    admission = _admission(inputs, evaluator=evaluator, budget=budget)
    inputs.clear()
    object.__setattr__(item, "size", True)
    object.__setattr__(evaluator, "kind", "bad;kind")
    object.__setattr__(budget, "max_processes", True)
    assert admission.inputs == (_input(),)
    assert admission.evaluator.kind == "exact"
    assert admission.budget.max_processes == 1


@pytest.mark.parametrize("mutation", [
    lambda a: object.__setattr__(a.inputs[0], "size", True),
    lambda a: object.__setattr__(a.inputs[0], "target", "."),
    lambda a: object.__setattr__(a.evaluator, "kind", "bad;kind"),
    lambda a: object.__setattr__(a.budget, "max_processes", True),
    lambda a: object.__setattr__(a, "inputs", [a.inputs[0]] * 65),
    lambda a: object.__setattr__(a, "evaluator", None),
    lambda a: object.__delattr__(a.budget, "max_output_bytes"),
])
def test_validation_digest_serialization_reconstruct_tampered_nested_dtos(mutation):
    admission = _admission([_input()])
    mutation(admission)
    for operation in [
        lambda: validate_candidate_execution_admission(admission),
        admission.digest, admission.to_dict,
        lambda: admit_candidate_execution(admission, plan=_plan()),
    ]:
        with pytest.raises(CandidateExecutionError):
            operation()


def test_overridden_dto_serializers_cannot_erase_invalid_raw_fields():
    class MisleadingInput(CandidateExecutionInput):
        def to_dict(self):
            return _input().to_dict()
    item = MisleadingInput("input", "fixture", 0, "f" * 64)
    object.__setattr__(item, "target", ".")
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_unsafe$"):
        _admission([item])


PIN_CASES = [
    ("expected_plan_sha256", "f" * 64, "plan_mismatch"),
    ("expected_bundle_sha256", "f" * 64, "bundle_mismatch"),
    ("expected_contract_sha256", "f" * 64, "contract_mismatch"),
    ("expected_dependency_sha256", "f" * 64, "dependency_mismatch"),
    ("expected_environment_sha256", "f" * 64, "environment_mismatch"),
    ("expected_evaluator_sha256", "f" * 64, "evaluator_mismatch"),
    ("expected_evaluator_kind", "another", "evaluator_mismatch"),
    ("expected_evaluator", {"kind": "another", "fingerprint": EVALUATOR}, "evaluator_mismatch"),
    ("expected_output_contract_sha256", "f" * 64, "output_contract_mismatch"),
    ("expected_admission_sha256", "f" * 64, "identity_mismatch"),
]


@pytest.mark.parametrize(("key", "value", "error"), PIN_CASES)
def test_replay_all_pin_mismatches_fail_before_any_input_io(monkeypatch, key, value, error):
    admission = _admission([_input()])
    plan = _plan()
    monkeypatch.setattr(files, "absolute_path", lambda *_a, **_kw: pytest.fail("input path touched"))
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("input root opened"))
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{error}$"):
        admit_candidate_execution(admission, plan=plan, input_root="/private/absent", **{key: value})


@pytest.mark.parametrize(("key", "value", "error"), PIN_CASES)
def test_build_all_pin_mismatches(key, value, error):
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{error}$"):
        _admission(**{key: value})


@pytest.mark.parametrize(("field", "error"), [
    ("workspace_plan_sha256", "plan_mismatch"),
    ("bundle_sha256", "bundle_mismatch"),
    ("contract_sha256", "contract_mismatch"),
])
def test_reference_mismatches_fail_before_io(monkeypatch, field, error):
    payload = _admission().to_dict(include_admission_sha256=False)
    payload[field] = "f" * 64
    admission = CandidateExecutionAdmission.from_dict(payload)
    monkeypatch.setattr(files, "absolute_path", lambda *_a, **_kw: pytest.fail("input path touched"))
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{error}$"):
        admit_candidate_execution(admission, plan=_plan(), input_root="/absent")


def test_replay_requires_plan_and_rejects_silently_ignored_declaration_fields():
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        admit_candidate_execution(_admission())
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_invalid$"):
        admit_candidate_execution(_admission(), plan=_plan(), dependency_sha256="f" * 64)


def test_plan_limits_fit_inside_admission_budget():
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
        _admission(budget=CandidateExecutionBudget(4, 1024, 1, 1))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_budget_invalid$"):
        _admission(budget=CandidateExecutionBudget(5, 1023, 1, 1))
    assert _admission(budget=CandidateExecutionBudget(6, 2048, 1, 1)).budget.timeout_seconds == 6


def test_plan_dto_tampering_is_replayed_without_io(monkeypatch):
    plan = _plan()
    object.__setattr__(plan, "environment", (("A", "one"), ("A", "two")))
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("file opened"))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        admit_candidate_execution(_admission(), plan=plan)


def test_raw_plan_source_fields_cannot_be_hidden_by_a_subclass_serializer():
    plan = _plan()
    original = plan.bundle.files[0]

    class MisleadingSource(CandidateSourceFile):
        def to_dict(self):
            return original.to_dict()

    misleading = MisleadingSource(original.path, original.size, original.sha256)
    object.__setattr__(misleading, "path", "../outside.py")
    object.__setattr__(plan.bundle, "files", (misleading,))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        admit_candidate_execution(_admission(), plan=plan)


def test_raw_plan_bundle_fields_cannot_be_hidden_by_a_subclass_serializer():
    plan = _plan()
    original = plan.bundle

    class MisleadingBundle(CandidateSourceBundle):
        def to_dict(self):
            return original.to_dict()

    misleading = MisleadingBundle(original.contract_sha256, original.entrypoint, original.files)
    object.__setattr__(misleading, "entrypoint", "missing.py")
    object.__setattr__(plan, "bundle", misleading)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        admit_candidate_execution(_admission(), plan=plan)


def test_verified_result_deep_reconstruction_and_observation_binding():
    admission = _admission([_input()])
    result = VerifiedCandidateExecutionAdmission(admission, admission.digest(), admission.inputs)
    object.__setattr__(admission.inputs[0], "size", True)
    assert result.observed_inputs == (_input(),)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_changed$"):
        VerifiedCandidateExecutionAdmission(_admission([_input()]), result.admission_sha256, ())
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_identity_mismatch$"):
        VerifiedCandidateExecutionAdmission(_admission(), "f" * 64, None)
