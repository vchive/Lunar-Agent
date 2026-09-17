"""The registered 128 case uses native snapshot execution and exact holdout scoring."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
from pathlib import Path

import pytest

from famou import candidate_execution_runner
from famou.data_profile import build_private_input_profile
from famou.evaluator_bundle import EvaluatorBundleError, compile_evaluator_bundle
from famou.runtime import RuntimeResult

CASE_PATH = (Path(__file__).resolve().parents[1]
             / "specs/128-format-admission-diagnostic/measurement/case.py")


@pytest.fixture
def case():
    spec = importlib.util.spec_from_file_location("measurement128_case", CASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Fresh synthetic source exercises the documented descriptor names. It does not
# reuse the private model-generated source retained by diagnostic 123.
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
            "files": [
                {"path": "data/raw/limit.json", "content": json.dumps({"limit": limit})},
                {"path": "output/result.json", "content": json.dumps({"value": value})},
            ],
        })
    return {"schema_version": "1", "constraint_coverage": ["valid-value"], "probes": probes,
            "score_order": [{"better": "high", "worse": "low"}]}


class FakeIsolatedRuntime:
    name = "offline128"

    def __init__(self, source=SOURCE):
        self.source = source
        self.calls = []

    def run(self, *args, **kwargs):
        pytest.fail("ordinary model runtime must not be invoked")

    def run_isolated(self, prompt, workspace, timeout=None):
        self.calls.append((prompt, workspace, timeout))
        if len(self.calls) == 1:
            return RuntimeResult(json.dumps({
                **suite(2), "objective": "Valid quality and score equal independently read value.",
                "evaluator_source": self.source,
            }))
        assert len(self.calls) == 2
        assert "adversarial evaluator auditor" in prompt
        return RuntimeResult(json.dumps(suite(4)))


def compiled(case, root, source=SOURCE):
    runtime = FakeIsolatedRuntime(source)
    inputs, profile = case.stage_inputs(root)
    bundle = compile_evaluator_bundle(
        runtime, case.contract(), root, inputs=inputs, timeout=2, invocation="snapshot",
    )
    return bundle, runtime, profile


def test_registered_contract_input_and_holdouts_are_exact_and_fresh(case, tmp_path):
    problem = case.contract()
    assert len(problem.hard_constraints) == 1
    assert problem.hard_constraints[0].id == "valid-value"
    assert problem.hard_constraints[0].verification_scope == "output"
    assert problem.hard_constraints[0].source_check is None
    inputs, profile = case.stage_inputs(tmp_path)
    assert (tmp_path / case.INPUT_PATH).read_bytes() == b'{"limit":3}\n'
    assert inputs[0].sha256 == hashlib.sha256(case.INPUT_BYTES).hexdigest()
    assert profile == build_private_input_profile(tmp_path, problem, inputs)
    assert (tmp_path / case.INPUT_PATH).stat().st_mode & 0o777 == 0o600
    definitions = case.holdouts()
    assert [(row["limit"], row["value"]) for row in definitions] == [
        (1, -1), (1, 0), (1, 1), (1, 2), (3, 0), (3, 2), (3, 3), (3, 4),
    ]
    for row in definitions:
        assert row["probe"]["files"] == [
            {"path": "data/raw/limit.json", "content": f'{{"limit":{row["limit"]}}}\n'},
            {"path": "output/result.json", "content": f'{{"value":{row["value"]}}}\n'},
        ]
        validity = int(0 <= row["value"] <= row["limit"])
        assert row["expected"] == {
            "validity": validity, "quality": row["value"] if validity else None,
            "combined_score": row["value"] if validity else 0,
            "constraint_code": None if validity else "valid-value",
        }
    assert json.loads(json.dumps(definitions)) == definitions
    definitions[0]["expected"]["validity"] = 99
    assert case.holdouts()[0]["expected"]["validity"] == 0
    with pytest.raises(FileExistsError):
        case.stage_inputs(tmp_path)


@pytest.mark.parametrize("symlink", ["root", "raw", "file"])
def test_staging_does_not_follow_existing_symlinks(case, tmp_path, symlink):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    if symlink == "root":
        workspace.symlink_to(outside, target_is_directory=True)
    elif symlink == "raw":
        (workspace / "data").mkdir(parents=True)
        (workspace / "data/raw").symlink_to(outside, target_is_directory=True)
    else:
        (workspace / "data/raw").mkdir(parents=True)
        (workspace / case.INPUT_PATH).symlink_to(outside / "limit.json")
    with pytest.raises(ValueError, match="symlink"):
        case.stage_inputs(workspace)
    assert list(outside.iterdir()) == []


def test_native_compiler_auditor_freeze_and_eight_snapshot_holdouts(case, tmp_path, monkeypatch):
    bundle, runtime, _ = compiled(case, tmp_path / "worker")
    before = {path.name: path.read_bytes() for path in bundle.root.iterdir()}
    executed = []
    real_process = candidate_execution_runner._bounded_process_bytes

    def process(command, **kwargs):
        root = Path(kwargs["cwd"])
        assert command[-2:] == ["evaluator.py", "request.json"]
        assert root.stat().st_mode & 0o777 == 0o700
        assert not (root / "candidate.py").exists()
        assert not (root / "execution.json").exists()
        assert not (root / "data").exists()
        executed.append(root.name)
        return real_process(command, **kwargs)

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", process)
    records = []
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts", record=records.append)
    assert rows == records
    assert executed == [row["name"] for row in case.holdouts()]
    assert len(runtime.calls) == 2
    assert all(row["status"] == "completed" and row["matched"] for row in rows)
    assert all(row["snapshot_started"] for row in rows)
    assert [row["observed"]["combined_score"] for row in rows] == [0, 0, 1, 0, 0, 2, 3, 0]
    assert "private-generated-text" not in json.dumps(rows)
    assert {path.name: path.read_bytes() for path in bundle.root.iterdir()} == before
    assert stat.S_IMODE((tmp_path / "holdouts").stat().st_mode) == 0o700
    with pytest.raises(FileExistsError):
        case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")
    assert len(executed) == 8


@pytest.mark.parametrize("change,matched", [
    ('"quality": value + 1 if valid else None', 3),
    ('"quality": value if valid else 1', 5),
    ('"quality": value if valid else None', 8),
])
def test_holdouts_recompute_exact_quality_beyond_native_probe_order(case, tmp_path, change, matched):
    source = SOURCE.replace('"quality": value if valid else None', change)
    bundle, _, _ = compiled(case, tmp_path / "worker", source)
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")
    assert sum(row["matched"] for row in rows) == matched
    assert all(row["status"] == "completed" for row in rows)


@pytest.mark.parametrize("old,new,matched", [
    ('"combined_score": value if valid else 0', '"combined_score": value + 1 if valid else 0', 3),
    ('0 <= value <= limit', '0 <= value <= limit + (1 if limit in (1, 3) else 0)', 6),
    ('0 <= value <= limit', '(1 if limit in (1, 3) else 0) <= value <= limit', 6),
    ('"code": "valid-value"', '"code": "other-rule" if limit in (1, 3) else "valid-value"', 5),
])
def test_native_holdouts_reject_wrong_score_bounds_and_constraint_code(case, tmp_path, old, new, matched):
    bundle, runtime, _ = compiled(case, tmp_path / "worker", SOURCE.replace(old, new))
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")
    assert len(runtime.calls) == 2
    assert len(rows) == 8
    assert sum(row["matched"] for row in rows) == matched
    assert all(row["status"] == "completed" for row in rows)
    assert "other-rule" not in json.dumps(rows)


def test_native_wrong_harness_failure_is_fixed_safe_and_runs_each_holdout_once(case, tmp_path):
    source = SOURCE.replace(
        '    valid = type(value) is int',
        '    if limit in (1, 3):\n'
        '        raise ValueError("private-generated-failure")\n'
        '    valid = type(value) is int',
    )
    bundle, runtime, _ = compiled(case, tmp_path / "worker", source)
    records = []
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts", record=records.append)
    assert rows == records
    assert len(rows) == 8 and len(runtime.calls) == 2
    assert all(row["status"] == "failed" and row["snapshot_started"] for row in rows)
    assert all(row["error_class"] == "EvaluatorBundleError" for row in rows)
    assert all(row["matched"] is False and row["observed"] is None for row in rows)
    assert "private-generated-failure" not in json.dumps(rows)
    with pytest.raises(FileExistsError):
        case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")


def test_holdout_harness_failure_is_private_retained_once_and_does_not_skip_other_rows(case, tmp_path, monkeypatch):
    bundle, _, _ = compiled(case, tmp_path / "worker")
    original = case._snapshot_probe
    calls = []

    def probe(evaluator, definition, problem, workspace, timeout):
        calls.append(definition.name)
        if len(calls) == 1:
            raise EvaluatorBundleError("private-generated-prose sk-not-for-public-output")
        return original(evaluator, definition, problem, workspace, timeout)

    monkeypatch.setattr(case, "_snapshot_probe", probe)
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")
    assert len(calls) == len(set(calls)) == 8
    assert rows[0] == {
        "name": case.holdouts()[0]["name"], "status": "failed", "matched": False,
        "snapshot_started": True, "observed": None, "error_class": "EvaluatorBundleError",
    }
    assert sum(row["matched"] for row in rows) == 7
    assert "private-generated" not in json.dumps(rows)


def test_holdout_requires_invalid_constraint_code(case, tmp_path, monkeypatch):
    from dataclasses import replace

    bundle, _, _ = compiled(case, tmp_path / "worker")
    original = case._snapshot_probe

    def probe(*args):
        report = original(*args)
        if report.validity == 0:
            return replace(report, error_info=({"code": "wrong-code", "message": "private"},))
        return report

    monkeypatch.setattr(case, "_snapshot_probe", probe)
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts")
    assert sum(row["matched"] for row in rows) == 5
    assert all(row["observed"]["constraint_code_present"] is False for row in rows)
    assert "wrong-code" not in json.dumps(rows)


def test_bundle_integrity_is_checked_after_execution_and_stops_more_holdouts(case, tmp_path, monkeypatch):
    bundle, _, _ = compiled(case, tmp_path / "worker")
    original = case._snapshot_probe

    def probe(*args):
        report = original(*args)
        source = bundle.root / "evaluator.py"
        source.chmod(0o644)
        source.write_text("changed frozen source")
        source.chmod(0o444)
        return report

    monkeypatch.setattr(case, "_snapshot_probe", probe)
    records = []
    rows = case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts", record=records.append)
    assert rows == records
    assert len(rows) == 1
    assert rows[0]["status"] == "failed" and rows[0]["matched"] is False
    assert rows[0]["error_class"] == "EvaluatorBundleError"


def test_fingerprint_is_checked_before_creating_holdout_workspaces(case, tmp_path):
    from dataclasses import replace

    bundle, _, _ = compiled(case, tmp_path / "worker")
    with pytest.raises(EvaluatorBundleError, match="fingerprint"):
        case.audit_holdouts(replace(bundle, fingerprint="0" * 64), case.contract(), tmp_path / "holdouts")
    assert not (tmp_path / "holdouts").exists()


def test_guard_stops_after_persisted_row_and_record_failure_does_not_repeat(case, tmp_path):
    bundle, _, _ = compiled(case, tmp_path / "worker")
    records = []

    def guard():
        if records:
            raise RuntimeError("registered total deadline reached")

    with pytest.raises(RuntimeError, match="deadline"):
        case.audit_holdouts(bundle, case.contract(), tmp_path / "holdouts",
                            continuation_guard=guard, record=records.append)
    assert len(records) == 1
    assert len(list((tmp_path / "holdouts").iterdir())) == 1

    def record(row):
        raise OSError("recording failed")

    with pytest.raises(OSError, match="recording"):
        case.audit_holdouts(bundle, case.contract(), tmp_path / "other-holdouts", record=record)
    assert len(list((tmp_path / "other-holdouts").iterdir())) == 1
