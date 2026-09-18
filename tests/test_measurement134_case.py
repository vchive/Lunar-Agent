"""Small multi-file task validation and fresh local evaluator holdouts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.evaluator_bundle import EvaluatorBundleError, compile_evaluator_bundle
from famou.evolution import CandidateInputArtifact
from famou.runtime import RuntimeResult

CASE_PATH = (Path(__file__).resolve().parents[1]
             / "specs/134-budgeted-multifile-acceptance/measurement/case.py")

# Fresh local source: no historical private model response is loaded or replayed.
SOURCE = '''import json
import sys
from pathlib import Path

def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    assert request["protocol"] == "lunar-candidate-evaluation-request-v1"
    descriptor = next(item for item in request["inputs"] if item.get("target") == "limit.json")
    assert set(descriptor) == {"target", "source_label", "size", "sha256"}
    output = next(item for item in request["outputs"] if item["path"] == "output/result.json")
    assert set(output) == {"path", "present", "size", "sha256"}
    limit = json.loads((Path("inputs") / descriptor["target"]).read_text())["limit"]
    value = json.loads(Path(output["path"]).read_text())["value"]
    valid = type(value) is int and 0 <= value <= limit
    print(json.dumps({
        "schema_version": "1", "evaluator_id": "compiled-bundle",
        "validity": int(valid), "quality": value if valid else None,
        "combined_score": value if valid else 0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "valid-value", "message": "private-generated-text"}],
    }))

if __name__ == "__main__":
    main()
'''


def suite(limit):
    probes = []
    for name, value, validity in (("low", 0, 1), ("high", limit, 1), ("invalid", limit + 1, 0)):
        probes.append({
            "name": name, "constraint_id": None if validity else "valid-value",
            "expected_validity": validity,
            "files": [{"path": "data/raw/limit.json", "content": json.dumps({"limit": limit})},
                      {"path": "output/result.json", "content": json.dumps({"value": value})}],
        })
    return {"schema_version": "1", "constraint_coverage": ["valid-value"], "probes": probes,
            "score_order": [{"better": "high", "worse": "low"}]}


class FakeIsolatedRuntime:
    name = "offline134"

    def __init__(self, source=SOURCE):
        self.source, self.calls = source, []

    def run(self, *args, **kwargs):
        pytest.fail("ordinary model runtime must not be invoked")

    def run_isolated(self, prompt, workspace, timeout=None):
        self.calls.append((prompt, workspace, timeout))
        if len(self.calls) == 1:
            return RuntimeResult(json.dumps({
                **suite(2), "objective": "Valid quality and score equal independently read value.",
                "evaluator_source": self.source,
            }))
        assert len(self.calls) == 2 and "adversarial evaluator auditor" in prompt
        return RuntimeResult(json.dumps(suite(4)))


@pytest.fixture
def case():
    spec = importlib.util.spec_from_file_location("measurement134_case", CASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_contract():
    """Fresh offline compiler fixture; never supplied to the measurement's real solve."""
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "offline134", "problem_type": "continuous",
        "statement": "Read limit.json and maximize an integer value within [0, limit].",
        "inputs": [{"path": "limit.json", "format": "json", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [
            {"id": "valid-value", "description": "An integer, excluding booleans and floats, within [0, limit].",
             "source": "user_confirmed", "verification": "independent", "verification_scope": "output",
             "result_fields": ["value"]},
            {"id": "python-files", "description": "At least two lowercase .py paths.",
             "source": "user_confirmed", "verification": "independent", "verification_scope": "source",
             "source_check": {"kind": "python_file_count", "minimum": 2}},
        ],
        "soft_constraints": [], "success_criteria": ["Valid output, quality and combined_score equal value."],
        "deliverables": ["output/result.json"],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"], "required": True}],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 3},
    })


def compiled(case, root, source=SOURCE):
    problem = fixture_contract()
    path = root / case.INPUT_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(case.INPUT_BYTES)
    inputs = (CandidateInputArtifact(case.INPUT_PATH, len(case.INPUT_BYTES),
                                    hashlib.sha256(case.INPUT_BYTES).hexdigest()),)
    runtime = FakeIsolatedRuntime(source)
    bundle = compile_evaluator_bundle(runtime, problem, root, inputs=inputs, timeout=2, invocation="snapshot")
    return problem, bundle, runtime


def test_generated_contract_and_registered_task(case):
    assert case.INPUT_BYTES == b'{"limit":3}\n'
    assert case.INPUT_PATH == "data/raw/limit.json"
    assert case.validate_generated_contract(fixture_contract()) is None
    assert not hasattr(case, "contract") and not hasattr(case, "stage_inputs")
    assert "source_check={kind: python_file_count, minimum: 2}" in case.GOAL
    assert "verification_scope=output" in case.GOAL
    assert "Python type(value) is int" in case.GOAL
    definitions = case.holdouts()
    assert [(row["limit"], row["value"]) for row in definitions] == [
        (1, -1), (1, 0), (1, 1), (1, 2), (3, 0), (3, 2), (3, 3), (3, 4),
    ]
    for row in definitions:
        assert row["probe"]["files"] == [
            {"path": "data/raw/limit.json", "content": f'{{"limit":{row["limit"]}}}\n'},
            {"path": "output/result.json", "content": f'{{"value":{row["value"]}}}\n'},
        ]
    definitions[0]["expected"]["validity"] = 99
    assert case.holdouts()[0]["expected"]["validity"] == 0


@pytest.mark.parametrize("drift", [
    "input_path", "input_format", "input_fields", "input_key", "extra_input", "output_path", "output_format",
    "output_fields", "optional_output", "deliverables", "extra_output", "direction", "metrics", "strategy",
    "extra_constraint", "soft_constraint", "output_id", "output_scope", "output_verification", "result_fields",
    "source_id", "source_scope", "source_verification", "source_fields", "minimum",
])
def test_generated_contract_rejects_structural_scope_drift(case, drift):
    data = fixture_contract().to_dict()
    if drift == "input_path":
        data["inputs"][0]["path"] = "other.json"
    elif drift == "input_format":
        data["inputs"][0]["format"] = "text"
    elif drift == "input_fields":
        data["inputs"][0]["fields"]["other"] = "text"
    elif drift == "input_key":
        data["inputs"][0]["key"] = "limit"
    elif drift == "extra_input":
        data["inputs"].append({**data["inputs"][0], "path": "extra.json"})
    elif drift == "output_path":
        data["outputs"][0]["path"] = "output/other.json"
    elif drift == "output_format":
        data["outputs"][0]["format"] = "text"
    elif drift == "output_fields":
        data["outputs"][0]["fields"] = ["score"]
    elif drift == "optional_output":
        data["outputs"][0]["required"] = False
    elif drift == "deliverables":
        data["deliverables"].append("output/summary.json")
    elif drift == "extra_output":
        data["outputs"].append({**data["outputs"][0], "path": "output/extra.json"})
    elif drift == "direction":
        data["objective"]["direction"] = "minimize"
    elif drift == "metrics":
        data["objective"]["metrics"] = [{"name": "other", "direction": "maximize", "weight": 1}]
    elif drift == "strategy":
        data["evolution"]["strategy"] = "openevolve"
    elif drift == "extra_constraint":
        data["hard_constraints"].append({**data["hard_constraints"][0], "id": "extra"})
    elif drift == "soft_constraint":
        data["soft_constraints"].append({**data["hard_constraints"][0], "id": "extra"})
    elif drift in {"output_id", "output_scope", "output_verification", "result_fields"}:
        item = data["hard_constraints"][0]
        key, value = {"output_id": ("id", "other"), "output_scope": ("verification_scope", "execution"),
                      "output_verification": ("verification", "solver"), "result_fields": ("result_fields", [])}[drift]
        item[key] = value
    else:
        item = data["hard_constraints"][1]
        if drift == "source_scope":
            item.pop("source_check")
            item["verification_scope"] = "output"
        elif drift == "minimum":
            item["source_check"]["minimum"] = 1
        else:
            key, value = {"source_id": ("id", "other"), "source_verification": ("verification", "partial"),
                          "source_fields": ("result_fields", ["value"])}[drift]
            item[key] = value
    with pytest.raises(ValueError):
        case.validate_generated_contract(AlgorithmProblemContract.from_dict(data))


@pytest.mark.parametrize("content,quality", [
    (b'{"value":0}', 0), (b'{"value":2}', 2), (b'{"value":3}', 3), (b'{"value":-1}', None),
    (b'{"value":4}', None), (b'{"value":true}', None), (b'{"value":false}', None),
    (b'{"value":3.0}', None), (b'{"value":"3"}', None), (b'{"value":null}', None),
    (b'{"value":NaN}', None), (b'{"value":Infinity}', None), (b'{"value":[]}', None),
    (b'[]', None), (b'3', None), (b'{}', None), (b'not-json', None), (b'\xff', None),
])
def test_independent_oracle_excludes_bool_float_and_malformed_output(case, content, quality):
    assert case.independent_output(content) == {"validity": quality is not None, "quality": quality}


def test_fresh_native_compilation_and_eight_once_only_holdouts(case, tmp_path):
    problem, bundle, runtime = compiled(case, tmp_path / "prepared")
    before = {path.name: path.read_bytes() for path in bundle.root.iterdir()}
    records = []
    rows = case.audit_holdouts(bundle, problem, tmp_path / "holdouts", record=records.append)
    assert rows == records and len(rows) == 8 and len(runtime.calls) == 2
    assert all(row["matched"] and row["snapshot_started"] for row in rows)
    assert [row["observed"]["combined_score"] for row in rows] == [0, 0, 1, 0, 0, 2, 3, 0]
    assert "private-generated-text" not in json.dumps(rows)
    assert {path.name: path.read_bytes() for path in bundle.root.iterdir()} == before
    with pytest.raises(FileExistsError):
        case.audit_holdouts(bundle, problem, tmp_path / "holdouts")


def test_holdouts_recompute_scores_and_do_not_accept_probe_order_alone(case, tmp_path):
    source = SOURCE.replace('"quality": value if valid else None', '"quality": value + 1 if valid else None')
    problem, bundle, _ = compiled(case, tmp_path / "prepared", source)
    rows = case.audit_holdouts(bundle, problem, tmp_path / "holdouts")
    assert sum(row["matched"] for row in rows) == 3


def test_holdout_failures_are_safe_and_remaining_rows_run_once(case, tmp_path, monkeypatch):
    problem, bundle, _ = compiled(case, tmp_path / "prepared")
    original, calls = case._snapshot_probe, []

    def probe(*args):
        calls.append(args[1].name)
        if len(calls) == 1:
            raise EvaluatorBundleError("private-generated-error")
        return original(*args)

    monkeypatch.setattr(case, "_snapshot_probe", probe)
    rows = case.audit_holdouts(bundle, problem, tmp_path / "holdouts")
    assert len(calls) == len(set(calls)) == 8
    assert sum(row["matched"] for row in rows) == 7
    assert rows[0]["error_class"] == "EvaluatorBundleError"
    assert "private-generated" not in json.dumps(rows)


def test_holdout_integrity_drift_stops_after_first_retained_row(case, tmp_path, monkeypatch):
    problem, bundle, _ = compiled(case, tmp_path / "prepared")
    original = case._snapshot_probe

    def probe(*args):
        report = original(*args)
        source = bundle.root / "evaluator.py"
        source.chmod(0o644)
        source.write_text("changed source")
        return report

    monkeypatch.setattr(case, "_snapshot_probe", probe)
    rows = case.audit_holdouts(bundle, problem, tmp_path / "holdouts")
    assert len(rows) == 1 and rows[0]["matched"] is False


def test_deadline_stops_after_record_without_repeating_snapshot(case, tmp_path):
    problem, bundle, _ = compiled(case, tmp_path / "prepared")
    records = []

    def guard():
        if records:
            raise RuntimeError("deadline")

    with pytest.raises(RuntimeError, match="deadline"):
        case.audit_holdouts(bundle, problem, tmp_path / "holdouts", continuation_guard=guard, record=records.append)
    assert len(records) == len(list((tmp_path / "holdouts").iterdir())) == 1
