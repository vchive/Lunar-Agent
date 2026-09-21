"""Advertised snapshot descriptors agree with both native request-producing paths."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_frozen_evaluator_bundle import BundleRuntime

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution import evaluator_bundle as bundle
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation import _request_values, evaluate_candidate_execution
from lunar_evolution.candidate_evaluation_spec import (
    candidate_output_contract_sha256,
    canonical_json,
    parse_candidate_evaluation_spec,
)
from lunar_evolution.candidate_execution import (
    CandidateExecutionBudget,
    CandidateExecutionInput,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_execution_evidence import run_candidate_execution_recorded
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan
from lunar_evolution.evolution import CandidateInputArtifact

REQUEST_HEADER = (
    "Snapshot request shape (illustrative metadata; contract is expanded at runtime):\n"
)
INPUT_TARGET = "nested/message.txt"
RESULT_PATH = "output/result.json"
OPTIONAL_PATH = "output/optional/note.txt"

# Independent synthetic task: choose a padded byte length and minimize it. This source and
# its probes are new fixtures, unrelated to any retained model-generated diagnostic source.
HARNESS = '''import json
import sys
from pathlib import Path


def emit(valid, value, code):
    score = 1 / (1 + value) if valid else 0
    print(json.dumps({
        "schema_version": "1", "evaluator_id": "compiled-bundle", "validity": valid,
        "quality": score if valid else None, "combined_score": score,
        "detailed_scores": {},
        "error_info": [] if valid else [{"code": code, "message": "Invalid padded size."}],
    }))


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    descriptor = None
    for item in request["inputs"]:
        if item.get("target") == "nested/message.txt":
            descriptor = item
    if descriptor is None:
        emit(0, 0, "missing-input")
        return
    size = len((Path("inputs") / descriptor["target"]).read_bytes())
    output = None
    for item in request["outputs"]:
        if item["path"] == "output/result.json":
            output = item
    value = json.loads(Path(output["path"]).read_text())["value"]
    valid = int(type(value) is int and value >= size)
    emit(valid, value, "padded-size")


if __name__ == "__main__":
    main()
'''
SOLVER = b'''import json
import os
from pathlib import Path
size = len((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "nested/message.txt").read_bytes())
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": size}))
'''


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _contract():
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "padded-byte-size", "problem_type": "continuous",
        "statement": "Choose the smallest integer at least the input's UTF-8 byte length.",
        "inputs": [{"path": INPUT_TARGET, "format": "text", "fields": {"body": "text"}}],
        "decision_variables": ["padded byte size"],
        "objective": {"name": "padded byte size", "direction": "minimize"},
        "hard_constraints": [{
            "id": "padded-size", "description": "Value is an integer at least the byte length.",
            "source": "user_confirmed", "verification": "independent",
        }],
        "soft_constraints": [], "success_criteria": ["Minimum valid padded size"],
        "deliverables": [RESULT_PATH], "assumptions": [],
        "outputs": [
            {"path": RESULT_PATH, "format": "json", "fields": ["value"]},
            {"path": OPTIONAL_PATH, "format": "text", "required": False},
        ],
    })


def _envelope(source=HARNESS):
    return {
        "schema_version": "1",
        "objective": "For a valid integer value >= input byte length, maximize 1 / (1 + value).",
        "evaluator_source": source, "constraint_coverage": ["padded-size"],
        "probes": [{
            "name": name, "constraint_id": None if valid else "padded-size",
            "expected_validity": valid,
            "files": [
                {"path": "data/raw/" + INPUT_TARGET, "content": "abc"},
                {"path": RESULT_PATH, "content": json.dumps({"value": value})},
            ],
        } for name, value, valid in (("tight", 3, 1), ("padded", 7, 1), ("short", 2, 0))],
        "score_order": [{"better": "tight", "worse": "padded"}],
    }


def _prompt(compiler=True, profile=None):
    contract = _contract()
    profile = {} if profile is None else profile
    if compiler:
        return bundle._compiler_prompt(contract, profile, invocation="snapshot")
    return bundle._auditor_prompt(
        contract, profile, "Minimize padded byte length.", HARNESS, invocation="snapshot",
    )


def _advertised_request(compiler=True):
    prompt = _prompt(compiler)
    assert prompt.count(REQUEST_HEADER) == 1
    return json.JSONDecoder().raw_decode(prompt.split(REQUEST_HEADER, 1)[1])[0]


def _field_types(value):
    return {name: type(item) for name, item in value.items()}


def _assert_advertised_shape(request, example):
    """Compare observable keys/types, leaving task values and opaque identities variable."""
    _request_values(request)
    assert _field_types(request) == _field_types(example)
    for section in ("binding", "evaluator"):
        assert _field_types(request[section]) == _field_types(example[section])
    assert all(type(item) is str for item in request["evaluator"]["command"])
    assert all(type(item) is str for item in example["evaluator"]["command"])
    for evaluator in (request["evaluator"], example["evaluator"]):
        assert all(type(key) is type(value) is str for key, value in evaluator["environment"].items())
    for descriptor in request["inputs"]:
        assert _field_types(descriptor) == _field_types(example["inputs"][0])
        assert "path" not in descriptor
    output_variants = {item["present"]: item for item in example["outputs"]}
    assert set(output_variants) == {True, False}
    for descriptor in request["outputs"]:
        assert _field_types(descriptor) == _field_types(output_variants[descriptor["present"]])
        assert "target" not in descriptor


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
def test_advertised_request_accepts_native_parser_after_expanding_declared_placeholders(compiler):
    example = _advertised_request(compiler)
    assert example == bundle._snapshot_request_example()
    assert example["contract"] == {}
    assert any("/" in item["target"] for item in example["inputs"])
    request = copy.deepcopy(example)
    # Contract content and its dependent identities are explicitly placeholders. Retain
    # every advertised descriptor/evaluator key, type and example value when filling them.
    data = _contract().to_dict()
    data["inputs"] = [
        {"path": item["target"], "format": "text", "fields": {"body": "text"}}
        for item in request["inputs"]
    ]
    data["outputs"] = [
        {"path": item["path"], "format": "text", "required": item["present"]}
        for item in request["outputs"]
    ]
    contract = AlgorithmProblemContract.from_dict(data)
    evaluator = parse_candidate_evaluation_spec(request["evaluator"])
    request["contract"] = contract.to_dict()
    request["binding"].update(
        contract_sha256=contract.digest(), evaluator_fingerprint=evaluator.digest(),
        input_file_table_sha256=_sha(canonical_json(request["inputs"])),
        output_contract_sha256=candidate_output_contract_sha256(contract.outputs),
    )
    assert _request_values(request) == (contract, evaluator)


@pytest.mark.parametrize("compiler", [True, False], ids=["compiler", "auditor"])
def test_snapshot_prompt_separates_runtime_schema_from_single_task_context(compiler):
    profile = {"files": [{"path": "data/raw/" + INPUT_TARGET, "fields": ["body"]}]}
    prompt = _prompt(compiler, profile)
    assert prompt.count(json.dumps(_contract().to_dict(), ensure_ascii=False, sort_keys=True, indent=2)) == 1
    assert prompt.count(json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2)) == 1
    assert str(Path(sys.executable).resolve()) not in prompt
    assert str(Path.cwd()) not in prompt
    assert "Runtime inputs[] has no path field" in prompt
    assert "contract.inputs[].path equals that target" in prompt
    assert "profile.files[].path" in prompt
    assert "do not prepend output/" in prompt
    assert "source_label is not a file location" in prompt
    assert "size=0 does not mean absent" in prompt
    example = _advertised_request(compiler)
    assert "profile" not in example and "files" not in example


def _compile(runtime, root):
    content = "private structural input café\n".encode()
    path = root / "data/raw" / INPUT_TARGET
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return bundle.compile_evaluator_bundle(
        runtime, _contract(), root, timeout=2, invocation="snapshot",
        inputs=(CandidateInputArtifact("data/raw/" + INPUT_TARGET, len(content), _sha(content)),),
    )


def test_native_compiler_and_auditor_preflights_use_advertised_nested_target_and_output_paths(
    tmp_path, monkeypatch,
):
    requests, reports = [], []
    original = runner._bounded_process_bytes
    example = _advertised_request()

    def inspect(command, **kwargs):
        root = Path(kwargs["cwd"])
        request = json.loads((root / "request.json").read_bytes())
        _assert_advertised_shape(request, example)
        descriptor = request["inputs"][0]
        assert descriptor["target"] == request["contract"]["inputs"][0]["path"] == INPUT_TARGET
        assert (root / "inputs" / descriptor["target"]).read_bytes() == b"abc"
        assert not (root / "data").exists()
        assert request["outputs"] == [
            {"path": OPTIONAL_PATH, "present": False, "size": None, "sha256": None},
            {"path": RESULT_PATH, "present": True,
             "size": len((root / RESULT_PATH).read_bytes()),
             "sha256": _sha((root / RESULT_PATH).read_bytes())},
        ]
        assert not (root / OPTIONAL_PATH).exists()
        result = original(command, **kwargs)
        requests.append(request)
        reports.append(json.loads(result[0]))
        return result

    monkeypatch.setattr(runner, "_bounded_process_bytes", inspect)
    runtime = BundleRuntime(_envelope())
    frozen = _compile(runtime, tmp_path)
    assert frozen.invocation == "snapshot"
    assert runtime.bundle_calls == runtime.audit_calls == 1
    assert "private structural input" not in runtime.bundle_prompts[0] + runtime.audit_prompts[0]
    assert len(requests) == 6
    assert [(item["validity"], item["combined_score"]) for item in reports] == [
        (1, 0.25), (1, 0.125), (0, 0), (1, 0.25), (1, 0.125), (0, 0),
    ]


def test_fresh_path_lookup_mistake_rejects_first_valid_probe_before_auditor_or_freeze(tmp_path):
    source = HARNESS.replace('item.get("target")', 'item.get("path")')
    runtime = BundleRuntime(_envelope(source))
    with pytest.raises(bundle.EvaluatorBundleError, match="tight returned wrong validity"):
        _compile(runtime, tmp_path)
    assert runtime.bundle_calls == 1 and runtime.audit_calls == 0
    assert not (tmp_path / "evaluator-bundle").exists()


def _executed_candidate(root, content):
    root = root.resolve()
    workspace, inputs, evaluations = [root / name for name in ("workspace", "inputs", "evaluations")]
    for directory in (workspace, inputs, evaluations):
        directory.mkdir(parents=True)
    (workspace / "main.py").write_bytes(SOLVER)
    target = inputs / INPUT_TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    contract = _contract()
    source_bundle = CandidateSourceBundle(
        contract.digest(), "main.py", (CandidateSourceFile("main.py", len(SOLVER), _sha(SOLVER)),),
    )
    plan = build_candidate_workspace_plan(
        source_bundle, command=(str(Path(sys.executable).resolve()),),
        contract_sha256=contract.digest(), timeout_seconds=2, max_output_bytes=1024,
    )
    harness = HARNESS.encode()
    harness_path = root / "harness.py"
    harness_path.write_bytes(harness)
    evaluator = bundle._snapshot_spec(harness, 2)
    admission = build_candidate_execution_admission(
        plan, inputs=(CandidateExecutionInput(INPUT_TARGET, "opaque-label", len(content), _sha(content)),),
        dependency_sha256="b" * 64, environment_sha256="c" * 64, evaluator=evaluator.pin(),
        output_contract_sha256=candidate_output_contract_sha256(contract.outputs),
        budget=CandidateExecutionBudget(2, 1024, 1024, 1),
    )
    attempt = root / "attempt"
    record = run_candidate_execution_recorded(
        admission, plan=plan, workspace_path=workspace, input_path=inputs, attempt_path=attempt,
    )
    assert record.to_dict()["runner_result"]["status"] == "succeeded"
    return admission, {
        "plan": plan, "contract": contract, "evaluator": evaluator, "harness_path": harness_path,
        "workspace_path": workspace, "input_path": inputs, "attempt_path": attempt,
        "evaluation_root": evaluations, "expected_completion_sha256": record.completion_sha256,
    }


@pytest.mark.parametrize("content", ["café\n".encode(), b""], ids=["utf8-bytes", "zero-byte-input"])
def test_actual_evaluation_request_matches_advertised_shape_and_reads_exact_descriptor_paths(
    tmp_path, content,
):
    admission, arguments = _executed_candidate(tmp_path, content)
    result = evaluate_candidate_execution(admission, **arguments)
    request = json.loads((result.evaluation_path / "request.json").read_bytes())
    _assert_advertised_shape(request, _advertised_request())
    assert request["inputs"] == [{
        "target": INPUT_TARGET, "source_label": "opaque-label", "size": len(content),
        "sha256": _sha(content),
    }]
    assert (result.evaluation_path / "inputs" / INPUT_TARGET).read_bytes() == content
    assert not (result.evaluation_path / "inputs/opaque-label").exists()
    assert request["outputs"][0] == {
        "path": OPTIONAL_PATH, "present": False, "size": None, "sha256": None,
    }
    assert request["outputs"][1]["path"] == RESULT_PATH
    assert not (result.evaluation_path / "output" / RESULT_PATH).exists()
    assert result.to_dict()["harness_invoked"] is True
    assert result.report.validity == 1
    assert result.report.quality == result.report.combined_score == 1 / (1 + len(content))
    assert json.loads((result.evaluation_path / RESULT_PATH).read_bytes()) == {"value": len(content)}
