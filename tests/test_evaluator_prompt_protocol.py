"""Generated-evaluator instructions describe the exact existing wire protocol."""
from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE, _contract, _envelope
from test_snapshot_evaluator_bundle import SNAPSHOT_SOURCE
from test_source_check_contract import source_contract

from lunar_evolution import evaluator_bundle as bundle
from lunar_evolution.candidate_evaluation_spec import parse_candidate_evaluation_report

RESPONSE_HEADER = "Response shape (replace every placeholder with task-specific values):\n"
REPORT_HEADER = "Report shape examples (illustrative values, not task scores):\n"


def _embedded_json(prompt, header):
    assert prompt.count(header) == 1
    return json.JSONDecoder().raw_decode(prompt.split(header, 1)[1])[0]


def _prompt(compiler, invocation, contract=None, *, profile=None, source=None):
    contract = contract or _contract()
    profile = {} if profile is None else profile
    if compiler:
        return bundle._compiler_prompt(contract, profile, invocation=invocation)
    return bundle._auditor_prompt(
        contract, profile, "Minimize route cost.", source or SNAPSHOT_SOURCE,
        invocation=invocation,
    )


def _task_example(example, invocation):
    """Fill advertised slots, preserving every schema key/type and relationship."""
    value = copy.deepcopy(example)
    fixture = _envelope(SNAPSHOT_SOURCE if invocation == "snapshot" else EVALUATOR_SOURCE)
    if "objective" in value:
        value["objective"] = fixture["objective"]
        value["evaluator_source"] = fixture["evaluator_source"]
    value["constraint_coverage"] = fixture["constraint_coverage"]
    assert len(value["probes"]) == len(fixture["probes"]) == 3
    for sample, concrete in zip(value["probes"], fixture["probes"], strict=True):
        assert sample["expected_validity"] == concrete["expected_validity"]
        if sample["constraint_id"] is not None:
            sample["constraint_id"] = concrete["constraint_id"]
        for sample_file, concrete_file in zip(sample["files"], concrete["files"], strict=True):
            sample_file["path"] = concrete_file["path"]
            sample_file["content"] = concrete_file["content"]
    return value


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_advertised_response_shape_passes_exact_parser_and_real_preflight(tmp_path, compiler, invocation):
    prompt = _prompt(compiler, invocation)
    example = _embedded_json(prompt, RESPONSE_HEADER)
    assert example == bundle._response_example(compiler=compiler)
    value = _task_example(example, invocation)
    raw = json.dumps(value)
    if compiler:
        suite = bundle._parse_envelope(raw, _contract(), invocation=invocation).probe_suite()
    else:
        suite = bundle._parse_probe_suite(raw, _contract(), invocation=invocation)
        assert "evaluator_source" not in example and "objective" not in example
    source = SNAPSHOT_SOURCE if invocation == "snapshot" else EVALUATOR_SOURCE
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(source, encoding="utf-8")
    bundle._preflight(
        evaluator, suite, _contract(), tmp_path, 2, label="documented", invocation=invocation,
    )
    assert not (tmp_path / ".documented-preflight").exists()


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_advertised_report_examples_are_full_strict_reports(compiler, invocation):
    examples = _embedded_json(_prompt(compiler, invocation), REPORT_HEADER)
    assert examples == bundle._report_examples()
    assert set(examples) == {"valid", "invalid"}
    for name, expected_validity in (("valid", 1), ("invalid", 0)):
        report = parse_candidate_evaluation_report(
            json.dumps(examples[name]).encode(), evaluator_id="compiled-bundle",
        )
        assert report.validity == expected_validity
        if expected_validity:
            assert report.combined_score > 0
            assert report.detailed_scores["objective"] == {"value": 1, "direction": "maximize"}
        else:
            assert report.combined_score == 0
            assert report.error_info[0]["code"] == "constraint-id"


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
def test_source_requirements_stay_outside_advertised_output_probe_coverage(tmp_path, compiler):
    contract = source_contract()
    prompt = _prompt(compiler, "snapshot", contract)
    assert 'exactly these output constraint IDs: ["serve-all"]' in prompt
    assert "independently checked source IDs" in prompt
    example = _task_example(_embedded_json(prompt, RESPONSE_HEADER), "snapshot")
    if compiler:
        suite = bundle._parse_envelope(json.dumps(example), contract, invocation="snapshot").probe_suite()
    else:
        suite = bundle._parse_probe_suite(json.dumps(example), contract, invocation="snapshot")
    assert suite.constraint_coverage == ("serve-all",)
    assert all(probe.constraint_id != "two-files" for probe in suite.probes)
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(SNAPSHOT_SOURCE, encoding="utf-8")
    bundle._preflight(evaluator, suite, contract, tmp_path, 2, label="source-output", invocation="snapshot")


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_task_context_is_preserved_as_data_with_protocol_words(compiler, invocation):
    marker = "every hard constraint per hard constraint Canonical contract: marker"
    contract = replace(_contract(), statement=marker)
    profile = {"field_names": [marker]}
    prompt = _prompt(compiler, invocation, contract, profile=profile)
    assert json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) in prompt
    assert json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2) in prompt
    assert prompt.count(marker) == 2


def test_auditor_receives_source_but_no_compiler_self_probe_values():
    source = SNAPSHOT_SOURCE + "\n# FROZEN_SOURCE_MARKER\n"
    prompt = _prompt(False, "snapshot", source=source)
    assert source in prompt
    assert "FROZEN_SOURCE_MARKER" in prompt
    assert "valid-low-cost" not in prompt
    assert "valid-high-cost" not in prompt
    assert "private-real-order" not in prompt


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
def test_snapshot_instructions_keep_runtime_and_probe_paths_separate(compiler):
    prompt = _prompt(compiler, "snapshot")
    assert "receives a candidate path" not in prompt
    assert "lunar-candidate-evaluation-request-v1" in prompt
    assert "inputs/<target>" in prompt
    assert "data/raw/<target>" in prompt
    assert "request.json" in prompt
    assert "synthetic" in prompt.lower()
    assert "schema" in prompt.lower()


def test_report_and_response_examples_return_fresh_values():
    first = bundle._response_example(compiler=True)
    first["probes"][0]["files"][0]["content"] = "MUTATED"
    first["constraint_coverage"].append("MUTATED")
    assert "MUTATED" not in json.dumps(bundle._response_example(compiler=True))
    report = bundle._report_examples()
    report["invalid"]["error_info"][0]["message"] = "MUTATED"
    assert "MUTATED" not in json.dumps(bundle._report_examples())


def test_source_policy_advertises_exact_import_allowlist_accepted_by_validator():
    policy = bundle._source_policy_prompt()
    imports = json.JSONDecoder().raw_decode(policy.split("code with imports from ", 1)[1])[0]
    assert imports == sorted(bundle._ALLOWED_IMPORTS)
    for module in imports:
        bundle._validate_source(f'import {module}\nif __name__ == "__main__":\n    pass\n')
    assert "re" not in imports
    with pytest.raises(bundle.EvaluatorBundleError, match="forbidden import"):
        bundle._validate_source('import re\nif __name__ == "__main__":\n    pass\n')


@pytest.mark.parametrize(
    "expression, rule",
    [
        ('open("output/result.json")', "open"),
        ('getattr({}, "keys")', "getattr"),
        ('"abc".replace("a", "b")', "replace"),
        ('Path("output/result.json").write_text("x")', "write_text"),
    ],
)
def test_advertised_source_restrictions_match_static_rejections(expression, rule):
    policy = bundle._source_policy_prompt()
    assert f'"{rule}"' in policy
    with pytest.raises(bundle.EvaluatorBundleError, match="forbidden"):
        bundle._validate_source(
            f'from pathlib import Path\nif __name__ == "__main__":\n    {expression}\n',
        )


@pytest.mark.parametrize("reader", ['read_text()', 'read_bytes()', 'open("r")', 'open("rb")'])
def test_advertised_read_only_path_operations_pass_source_validation(reader):
    bundle._validate_source(
        f'from pathlib import Path\nif __name__ == "__main__":\n'
        f'    Path("output/result.json").{reader}\n',
    )


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
def test_advertised_required_and_allowed_paths_come_from_contract(compiler):
    base = _contract()
    contract = replace(
        base,
        inputs=(*base.inputs, replace(base.inputs[0], path="nested/more.csv")),
        outputs=(*base.outputs, replace(base.outputs[0], path="output/optional.csv", required=False)),
    )
    prompt = _prompt(compiler, "snapshot", contract)
    decoder = json.JSONDecoder()
    required = decoder.raw_decode(prompt.split("Every probe includes these paths: ", 1)[1])[0]
    allowed = decoder.raw_decode(prompt.split("Allowed paths are: ", 1)[1])[0]
    assert set(required) == {
        "data/raw/orders.csv", "data/raw/nested/more.csv", "output/routes.csv",
    }
    assert set(allowed) == {*required, "output/optional.csv"}
    assert "small" in prompt and "synthetic" in prompt
    assert "schema validation" in prompt.lower()


@pytest.mark.parametrize("literal", ["/message", "~label", "../message", "a/../b", "  /message  "])
def test_source_policy_explains_literal_checks_even_for_nonpath_strings(literal):
    policy = bundle._source_policy_prompt()
    assert "Every stripped string literal" in policy
    assert "not used as a filename" in policy
    with pytest.raises(bundle.EvaluatorBundleError, match="forbidden external path"):
        bundle._validate_source(
            f'if __name__ == "__main__":\n    print({literal!r})\n',
        )
