"""The independent evaluator declaration and exact report protocol are pure and bounded."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from lunar_evolution.algorithm import MAX_REPORT_BYTES, EvaluationReport, OutputSpec
from lunar_evolution.candidate_evaluation_spec import (
    MAX_CANDIDATE_EVALUATION_SPEC_BYTES,
    CandidateEvaluationError,
    CandidateEvaluationSpec,
    candidate_output_contract_sha256,
    canonical_json,
    parse_candidate_evaluation_report,
    parse_candidate_evaluation_spec,
    strict_json,
)
from lunar_evolution.candidate_execution import CandidateEvaluatorPin


def _spec(**kwargs):
    fields = {
        "harness_sha256": hashlib.sha256(b"print('report')").hexdigest(),
        "harness_size": len(b"print('report')"), "command": ("/absent/python", "-I"),
    }
    fields.update(kwargs)
    return CandidateEvaluationSpec(**fields)


def _report():
    return EvaluationReport(
        schema_version="1", evaluator_id="exact", validity=1, combined_score=0.75,
        detailed_scores={"utilization": {"value": 0.75, "direction": "maximize"}},
        error_info=(), quality=0.75,
    ).to_dict()


def test_spec_roundtrip_and_fingerprint_are_pure_memory_and_detached(monkeypatch):
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("opened a file"))
    monkeypatch.setattr(Path, "stat", lambda *_a, **_kw: pytest.fail("inspected a runner"))
    monkeypatch.setenv("LUNAR_EVALUATOR_TEST_SECRET", "must-not-capture")
    command = ["/absent/python", "-I"]
    environment = {"Z": "", "A": "你好"}
    spec = _spec(command=command, environment=environment, timeout_seconds=30)
    payload = spec.to_dict()
    assert payload["schema_version"] == "1"
    assert payload["protocol"] == "lunar-candidate-evaluator-v1"
    assert payload["max_report_bytes"] == MAX_REPORT_BYTES
    assert spec.timeout_seconds == 30.0
    assert spec.environment == (("A", "你好"), ("Z", ""))
    assert spec.digest() == hashlib.sha256(canonical_json(payload)).hexdigest()
    assert spec.pin() == CandidateEvaluatorPin("command-exact-v1", spec.digest())
    for source in (spec, payload, MappingProxyType(payload), json.dumps(payload), canonical_json(payload)):
        parsed = parse_candidate_evaluation_spec(source)
        assert parsed == spec
        assert parsed is not spec
    command.append("mutation")
    environment["A"] = "mutation"
    payload["command"].append("mutation")
    payload["environment"]["A"] = "mutation"
    assert spec.command == ("/absent/python", "-I")
    assert dict(spec.environment) == {"A": "你好", "Z": ""}


@pytest.mark.parametrize("changes", [
    {"harness_sha256": "a" * 64}, {"harness_size": 123},
    {"command": ("/other/python", "-I")}, {"command": ("/absent/python", "-B")},
    {"evaluator_id": "other"}, {"environment": (("A", "value"),)},
    {"timeout_seconds": 31}, {"max_output_file_bytes": 100},
    {"max_total_output_bytes": 32 * 1024 * 1024},
])
def test_fingerprint_binds_each_effective_evaluator_declaration(changes):
    assert _spec(**changes).pin() != _spec().pin()


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("harness_sha256"), lambda p: p.update(unknown=1),
    lambda p: p.update(schema_version=1), lambda p: p.update(schema_version="2"),
    lambda p: p.update(protocol="other"), lambda p: p.update(max_report_bytes=16384),
    lambda p: p.update(max_report_bytes=32768.0),
    lambda p: p.update(command=("/bin/python",)), lambda p: p.update(environment=[]),
    lambda p: p.update(harness_sha256="A" * 64), lambda p: p.update(harness_sha256="a" * 63),
    lambda p: p.update(evaluator_id=""), lambda p: p.update(evaluator_id="../secret"),
    lambda p: p.update(evaluator_id=" exact "), lambda p: p.update(evaluator_id="\ud800"),
])
def test_spec_rejects_inexact_schema_and_invalid_identity(mutation):
    payload = _spec().to_dict()
    mutation(payload)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        CandidateEvaluationSpec.from_dict(payload)


@pytest.mark.parametrize("command", [
    (), "python", ("python",), ("./python",), ("/bin/../python",),
    ("/bin//python",), ("/bin/./python",), ("/bin/python", "\x00"),
    ("/bin/python", "\ud800"), ("/bin/python", "é" * 2049), ("/bin/python",) * 33,
])
def test_command_uses_existing_bounded_absolute_declaration_policy(command):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        _spec(command=command)


@pytest.mark.parametrize("environment", [
    None, {"": "value"}, {"A=B": "value"}, {"A/B": "value"}, {"A": "\x00"},
    {"A": "\ud800"}, {"A": "x" * 4097}, {"A" * 257: ""},
    {f"A{i}": "" for i in range(129)}, (("A", "1"), ("A", "2")),
])
def test_environment_rejects_invalid_or_duplicate_pairs(environment):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        _spec(environment=environment)


@pytest.mark.parametrize("timeout", [
    True, None, "3", 0, -1, float("inf"), float("nan"), 86401,
    pytest.param(10**10000, id="overflow"),
])
def test_timeout_is_finite_and_within_declared_bounds(timeout):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        _spec(timeout_seconds=timeout)


@pytest.mark.parametrize(("field", "value"), [
    ("harness_size", True), ("harness_size", 0), ("harness_size", 1024 * 1024 + 1),
    ("harness_size", 1.0), ("max_output_file_bytes", True), ("max_output_file_bytes", 0),
    ("max_output_file_bytes", 16 * 1024 * 1024 + 1), ("max_total_output_bytes", 0),
    ("max_total_output_bytes", 64 * 1024 * 1024 + 1),
    ("max_total_output_bytes", 16 * 1024 * 1024 - 1),
])
def test_artifact_and_harness_sizes_have_positive_integer_bounds(field, value):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        _spec(**{field: value})


def test_exact_limits_and_full_command_capacity_are_accepted():
    spec = _spec(
        harness_size=1024 * 1024, timeout_seconds=86400,
        command=("/absent/python",) + ("",) * 31,
        max_output_file_bytes=16 * 1024 * 1024, max_total_output_bytes=64 * 1024 * 1024,
    )
    assert parse_candidate_evaluation_spec(spec) == spec
    assert _spec(timeout_seconds=30).digest() == _spec(timeout_seconds=30.0).digest()


@pytest.mark.parametrize(("field", "value"), [
    ("harness_sha256", "bad"), ("command", ("relative",)),
    ("environment", (("A", "1"), ("A", "2"))), ("timeout_seconds", float("nan")),
])
def test_mutated_spec_is_revalidated_before_serialization_and_fingerprinting(field, value):
    spec = _spec()
    object.__setattr__(spec, field, value)
    for operation in (spec.to_dict, spec.digest, spec.pin, lambda: parse_candidate_evaluation_spec(spec)):
        with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
            operation()


@pytest.mark.parametrize("source", ["/private/sensitive.json", Path("/private/sensitive.json"), b"{}", 1, None])
def test_parse_source_is_never_interpreted_as_a_path(source, monkeypatch):
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("opened a file"))
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        parse_candidate_evaluation_spec(source)


def test_output_contract_digest_sorts_and_preserves_output_semantics():
    outputs = [
        OutputSpec("output/z.txt", "text", required=False, description="optional notes"),
        OutputSpec("output/data/a.json", "json", ("items", "score")),
    ]
    expected = [item.to_dict() for item in sorted(outputs, key=lambda item: item.path)]
    fingerprint = candidate_output_contract_sha256(outputs)
    assert fingerprint == hashlib.sha256(canonical_json(expected)).hexdigest()
    assert candidate_output_contract_sha256(tuple(reversed(outputs))) == fingerprint
    outputs[0] = OutputSpec("output/z.txt", "text", required=True)
    assert candidate_output_contract_sha256(outputs) != fingerprint


@pytest.mark.parametrize("paths", [
    ("output/a", "output/a"), ("output/A", "output/a"),
    ("output/a", "output/a/b"), ("output/a/b", "output/a"),
    ("output/A/one", "output/a/two"), ("output/Straße", "output/STRASSE"),
])
def test_output_contract_rejects_case_aliases_duplicates_and_file_directory_collisions(paths):
    outputs = [OutputSpec(path, "text") for path in paths]
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        candidate_output_contract_sha256(outputs)


@pytest.mark.parametrize("path", [
    "output/.git/a", "output/.GIT/a", "output/a:b", "output/a\n", "output/e\u0301",
    "output/../outside", "/output/a", "output//a", "output/a\\b", "output/\ud800",
])
def test_output_contract_rechecks_portable_path_policy_on_mutated_dtos(path):
    output = OutputSpec("output/result.txt", "text")
    object.__setattr__(output, "path", path)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        candidate_output_contract_sha256((output,))


@pytest.mark.parametrize(("field", "value"), [
    ("fields", "score"), ("fields", ("x", "x")), ("format", "unsupported"),
    ("required", 1), ("description", 123),
])
def test_output_contract_rebuilds_mutated_dtos(field, value):
    output = OutputSpec("output/result.json", "json")
    object.__setattr__(output, field, value)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        candidate_output_contract_sha256((output,))


@pytest.mark.parametrize("outputs", [(), None, "output/result.txt", ({"path": "output/a"},), (None,)])
def test_output_contract_requires_a_nonempty_outputspec_sequence(outputs):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        candidate_output_contract_sha256(outputs)


def test_output_contract_count_is_bounded():
    outputs = [OutputSpec(f"output/file-{index}.txt", "text") for index in range(33)]
    assert candidate_output_contract_sha256(outputs[:32])
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        candidate_output_contract_sha256(outputs)


def test_report_parser_reuses_algorithm_report_semantics_and_returns_detached_data():
    value = _report()
    report = parse_candidate_evaluation_report(canonical_json(value), evaluator_id="exact")
    assert report == EvaluationReport.from_dict(value)
    value["detailed_scores"]["utilization"]["value"] = 0
    assert report.detailed_scores["utilization"]["value"] == 0.75
    invalid = _report()
    invalid.update(validity=0, combined_score=0, quality=None)
    invalid["error_info"] = [{"code": "overlap", "message": "Pieces overlap."}]
    assert parse_candidate_evaluation_report(canonical_json(invalid), evaluator_id="exact").validity == 0


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("quality"), lambda p: p.pop("error_info"), lambda p: p.update(unknown=True),
    lambda p: p.update(schema_version=1), lambda p: p.update(schema_version="2"),
    lambda p: p.update(evaluator_id="other"), lambda p: p.update(evaluator_id=" exact "),
    lambda p: p.update(validity=True), lambda p: p.update(validity=1.0), lambda p: p.update(validity=2),
    lambda p: p.update(validity=0), lambda p: p.update(validity=0, combined_score=0),
    lambda p: p.update(combined_score=-1), lambda p: p.update(combined_score=True),
    lambda p: p.update(quality=-1), lambda p: p.update(quality="1"),
    lambda p: p.update(error_info={}),
    lambda p: p.update(error_info=[{"code": "bad", "message": "bad", "extra": "bad"}]),
    lambda p: p.update(detailed_scores={"cost": {"value": 1, "direction": "other"}}),
    lambda p: p.update(detailed_scores={"cost": {"value": True, "direction": "minimize"}}),
    lambda p: p.update(detailed_scores={"cost": {"value": 1, "direction": "minimize", "extra": 0}}),
])
def test_report_rejects_inexact_schema_wrong_identity_and_invalid_scores(mutation):
    payload = _report()
    mutation(payload)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_report_invalid$"):
        parse_candidate_evaluation_report(canonical_json(payload), evaluator_id="exact")


@pytest.mark.parametrize("content", [
    b'[]', b'null', b'{"schema_version":"1","schema_version":"1"}',
    b'{"x":{"duplicate":1,"duplicate":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'{"x":1e999}', b'{"x":"\\ud800"}', b'"\xff"',
    b'\xef\xbb\xbf{}', b'{} trailing',
    pytest.param(b'[' * 2000 + b']' * 2000, id="deeply-nested-array"),
    "{}", bytearray(b"{}"),
])
def test_report_rejects_malformed_utf8_duplicates_and_nonfinite_json(content):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_report_invalid$"):
        parse_candidate_evaluation_report(content, evaluator_id="exact")


def test_report_accepts_more_than_16k_and_exact_32k_without_truncation():
    payload = _report()
    payload["detailed_scores"] = {
        f"metric_{index}_" + "x" * 490: {"value": index, "direction": "maximize"}
        for index in range(32)
    }
    content = canonical_json(payload)
    assert 16 * 1024 < len(content) < MAX_REPORT_BYTES
    report = parse_candidate_evaluation_report(content, evaluator_id="exact")
    assert len(report.detailed_scores) == 32
    padded = content + b" " * (MAX_REPORT_BYTES - len(content))
    assert parse_candidate_evaluation_report(padded, evaluator_id="exact") == report
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_report_invalid$"):
        parse_candidate_evaluation_report(padded + b" ", evaluator_id="exact")


def test_strict_json_helpers_accept_any_root_and_bound_original_bytes():
    for value in (None, True, 4, 0.5, "你好", [1, {"a": 2}], {"z": [], "a": {}}):
        encoded = canonical_json(value)
        assert strict_json(encoded) == value
        assert strict_json(encoded.decode()) == value
    assert canonical_json({"z": "你好", "a": 2}) == '{"a":2,"z":"你好"}'.encode()
    assert strict_json(b"1e10", maximum=4) == 10**10
    assert canonical_json(None, maximum=4) == b"null"
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        canonical_json(None, maximum=3)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        strict_json(b"null ", maximum=4)


@pytest.mark.parametrize("content", [
    b'{"a":1,"a":2}', b'[0,{"a":1,"a":2}]', b'NaN', b'Infinity', b'-Infinity',
    b'1e9999', b'"\\ud800"', b'"\xff"', b'null garbage', b'\xef\xbb\xbfnull',
    pytest.param(b"1" * 5000, id="excessive-integer"),
])
def test_strict_json_rejects_unbounded_or_ambiguous_content_with_fixed_errors(content):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        strict_json(content)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "\ud800", {"a": float("-inf")}, object()])
def test_canonical_json_rejects_non_json_or_invalid_unicode_values(value):
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        canonical_json(value)


def test_json_helpers_handle_cycles_and_enforce_the_spec_byte_limit():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        canonical_json(cyclic)
    content = b" " * MAX_CANDIDATE_EVALUATION_SPEC_BYTES + canonical_json(_spec().to_dict())
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        parse_candidate_evaluation_spec(content)


def test_json_helpers_map_runtime_recursion_errors(monkeypatch):
    def exhausted(*_args, **_kwargs):
        raise RecursionError("private implementation detail")

    monkeypatch.setattr(json, "loads", exhausted)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        strict_json(b"[]")
    monkeypatch.setattr(json, "dumps", exhausted)
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_invalid$"):
        canonical_json([])


@pytest.mark.parametrize("code", ["/private/secret", "candidate_evaluation_/private/secret", None])
def test_error_codes_never_echo_unrecognized_caller_text(code):
    error = CandidateEvaluationError(code)
    assert error.code == str(error) == "candidate_evaluation_invalid"


def test_known_error_codes_support_prefix_or_suffix():
    assert str(CandidateEvaluationError("report_invalid")) == "candidate_evaluation_report_invalid"
    assert str(CandidateEvaluationError("candidate_evaluation_report_invalid")) == "candidate_evaluation_report_invalid"
