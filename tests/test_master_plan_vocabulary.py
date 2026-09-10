"""Public vocabulary does not replace structural, credential or artifact authority checks."""

import hashlib
import json
from pathlib import Path

import pytest
from test_workflow_checkpoint import _manifest

from famou.workflow_checkpoint import AggregateUsage, WorkflowCheckpointError, WorkflowController


def _rewrite_master(controller: WorkflowController, **changes: object) -> None:
    path = controller.workflow / "master.json"
    payload = json.loads(path.read_text())
    payload.update(changes)
    body = {key: value for key, value in payload.items() if key != "plan_sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    payload["plan_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("step", [
    "Implement an objective scorer and maximize combined_score from the public formula.",
    "Save a baseline heuristic before refinement.",
    "Use a public evaluator for local feasibility checks.",
    "Build a local test harness for the generated candidate.",
    "Do not access private data or expose credentials.",
    "Keep the SCORE calculation consistent with the public objective.",
])
def test_public_plan_vocabulary_round_trips(tmp_path: Path, step: str) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    payload = controller.write_master([step], ["candidate.py"])
    assert controller.load_master() == payload
    assert payload["plan"] == [step]
    assert controller.state()["stage"] == "master_ready"
    assert not (controller.workspace / "receipt.json").exists()


@pytest.mark.parametrize("name", [
    "scorer.py", "baseline_solution.py", "public_evaluator.py", "test_harness.py",
    "private_notes.md", "credential_report.txt",
])
def test_ordinary_output_names_round_trip(tmp_path: Path, name: str) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    payload = controller.write_master(["Implement the public task."], [name])
    assert controller.load_master() == payload
    assert payload["expected_paths"] == [name]


@pytest.mark.parametrize("changes", [
    {"plan": ["Implement the public objective scorer and combined_score."]},
    {"expected_paths": ["baseline_solution.py", "scorer.py"]},
])
def test_loading_also_accepts_public_vocabulary(tmp_path: Path, changes: dict) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    controller.write_master(["Implement the public task."], ["candidate.py"])
    _rewrite_master(controller, **changes)
    loaded = controller.load_master()
    assert all(loaded[key] == value for key, value in changes.items())


@pytest.mark.parametrize("plan", [[], "step", [None], [""], ["x\x00y"], ["字" * 683], ["step"] * 65])
def test_plan_shape_and_bounds_remain_checked_on_write_and_read(tmp_path: Path, plan: object) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    with pytest.raises(WorkflowCheckpointError, match="bounded|invalid master plan"):
        controller.write_master(plan, [])
    assert not (controller.workflow / "master.json").exists()
    controller.write_master(["Implement the public task."], [])
    _rewrite_master(controller, plan=plan)
    with pytest.raises(WorkflowCheckpointError, match="bounded|invalid master plan"):
        controller.load_master()


@pytest.mark.parametrize("paths", [
    ["/absolute/scorer.py"], ["../scorer.py"], ["dir/../scorer.py"], ["./scorer.py"],
    ["dir//scorer.py"], ["scorer.py/"], ["dir\\scorer.py"], ["candidate.py", "candidate.py"],
])
def test_output_path_boundaries_remain_checked_on_write_and_read(tmp_path: Path, paths: list) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    with pytest.raises(WorkflowCheckpointError, match="confined POSIX|unique"):
        controller.write_master(["Implement the public task."], paths)
    assert not (controller.workflow / "master.json").exists()
    controller.write_master(["Implement the public task."], ["candidate.py"])
    _rewrite_master(controller, expected_paths=paths)
    with pytest.raises(WorkflowCheckpointError, match="confined POSIX|invalid expected paths"):
        controller.load_master()


@pytest.mark.parametrize("field", ["score", "overall_score", "validity_score"])
def test_resigned_score_fields_cannot_enter_control_schema(tmp_path: Path, field: str) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    controller.write_master(["Implement the public task."], [])
    _rewrite_master(controller, **{field: 1.0})
    with pytest.raises(WorkflowCheckpointError, match="invalid fields"):
        controller.load_master()
    assert not (controller.workspace / "receipt.json").exists()


@pytest.mark.parametrize("credential", [
    "api_key=sk-1234567890", "Bearer abcdefgh1234", "password=fixture-password",
])
def test_detectable_credentials_remain_redacted_and_rejected_when_reinserted(
    tmp_path: Path, credential: str,
) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    payload = controller.write_master([f"Remember {credential}."], [])
    assert credential not in json.dumps(payload)
    assert "[REDACTED]" in payload["plan"][0]
    assert controller.load_master() == payload
    _rewrite_master(controller, plan=[f"Remember {credential}."])
    with pytest.raises(WorkflowCheckpointError, match="contains a credential"):
        controller.load_master()


@pytest.mark.parametrize("name", [
    "sk-1234567890.py", "api_key=fixture-key.py", "password=fixture-password.txt",
    "Bearer abcdefgh1234.py",
])
def test_credential_paths_are_rejected_without_renaming_on_write_and_read(
    tmp_path: Path, name: str,
) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    with pytest.raises(WorkflowCheckpointError, match="contains? a credential") as written:
        controller.write_master(["Implement the public task."], [name])
    assert name not in str(written.value)
    assert not (controller.workflow / "master.json").exists()
    controller.write_master(["Implement the public task."], ["candidate.py"])
    _rewrite_master(controller, expected_paths=[name])
    with pytest.raises(WorkflowCheckpointError, match="contains? a credential") as loaded:
        controller.load_master()
    assert name not in str(loaded.value)
    assert json.loads((controller.workflow / "master.json").read_text())["expected_paths"] == [name]


@pytest.mark.parametrize("changes", [{"run_id": "different-run"}, {"request_sha256": "0" * 64}])
def test_resigning_does_not_replace_master_identity(tmp_path: Path, changes: dict) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    controller.write_master(["Implement the public task."], [])
    _rewrite_master(controller, **changes)
    with pytest.raises(WorkflowCheckpointError, match="binding mismatch"):
        controller.load_master()


@pytest.mark.parametrize("link_parent", [False, True])
def test_newly_permitted_names_do_not_allow_symlink_artifacts(
    tmp_path: Path, link_parent: bool,
) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    name = "scorer/baseline_solution.py" if link_parent else "baseline_solution.py"
    controller.write_master(["Implement the public objective scorer."], [name])
    controller.transition("build_running")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "baseline_solution.py").write_text("fixture only", encoding="utf-8")
    if link_parent:
        (controller.workspace / "scorer").symlink_to(outside, target_is_directory=True)
    else:
        (controller.workspace / name).symlink_to(outside / name)
    with pytest.raises(WorkflowCheckpointError, match="symlink"):
        controller.checkpoint(
            stage="checkpointed", declared_paths=[name], usage=AggregateUsage.zero(),
        )
    assert controller.state()["stage"] == "build_running"
    assert not tuple(controller.checkpoints.iterdir())
