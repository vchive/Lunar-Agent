"""Independent filesystem drift and retained evaluation inspection boundaries."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from test_candidate_evaluation import fixture

from lunar_evolution import candidate_evaluation as evaluation
from lunar_evolution.candidate_evaluation_spec import CandidateEvaluationError, canonical_json


def original_path(request, role):
    return {
        "source": request["workspace_path"] / "solve/helper.py",
        "input": request["input_path"] / "value",
        "output": request["workspace_path"] / "output/result.json",
        "harness": request["harness_path"],
        "completion": request["attempt_path"] / "completed.json",
    }[role]


def replace_same_bytes(path):
    content = path.read_bytes()
    retained = path.with_name(path.name + ".original")
    path.rename(retained)
    path.write_bytes(content)
    retained.unlink()


def assert_incomplete(request):
    paths = list(request["evaluation_root"].iterdir())
    assert len(paths) == 1
    assert not (paths[0] / "evaluation.json").exists()
    with pytest.raises(CandidateEvaluationError, match="incomplete"):
        evaluation.inspect_candidate_evaluation(paths[0])
    assert (request["workspace_path"] / "count").read_text() == "x"
    return paths[0]


@pytest.mark.parametrize("role", ["source", "input", "output", "harness"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_unsafe_original_file_nodes_fail_without_harness_or_allocation(tmp_path, monkeypatch, role, kind):
    admission, request = fixture(tmp_path)
    path = original_path(request, role)
    retained = path.with_name(path.name + ".original")
    path.rename(retained)
    if kind == "symlink":
        path.symlink_to(retained.name)
    elif kind == "hardlink":
        os.link(retained, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    monkeypatch.setattr(evaluation, "_bounded_process_bytes", lambda *a, **k: pytest.fail("harness launched"))
    with pytest.raises(CandidateEvaluationError, match=role + "_changed"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("root", ["workspace_path", "input_path"])
def test_same_bytes_in_replaced_root_do_not_match_execution_intent(tmp_path, monkeypatch, root):
    admission, request = fixture(tmp_path)
    path = request[root]
    retained = path.with_name(path.name + "-original")
    path.rename(retained)
    shutil.copytree(retained, path)
    monkeypatch.setattr(evaluation, "_bounded_process_bytes", lambda *a, **k: pytest.fail("harness launched"))
    with pytest.raises(CandidateEvaluationError, match="identity_mismatch"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "file", "fifo"])
def test_optional_output_obstructed_parent_is_not_treated_as_absent(tmp_path, monkeypatch, kind):
    admission, request = fixture(tmp_path, outputs=[
        {"path": "output/result.json", "format": "json", "fields": ["value"]},
        {"path": "output/optional/detail.txt", "format": "text", "required": False},
    ])
    path = request["workspace_path"] / "output/optional"
    if kind == "symlink":
        path.symlink_to("absent")
    elif kind == "file":
        path.write_bytes(b"not a directory")
    else:
        os.mkfifo(path)
    monkeypatch.setattr(evaluation, "_bounded_process_bytes", lambda *a, **k: pytest.fail("harness launched"))
    with pytest.raises(CandidateEvaluationError, match="output_changed"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("role", ["source", "input", "output", "harness", "completion"])
def test_same_byte_original_replacement_during_harness_does_not_publish_result(tmp_path, monkeypatch, role):
    admission, request = fixture(tmp_path)
    process = evaluation._bounded_process_bytes

    def changed(*args, **kwargs):
        result = process(*args, **kwargs)
        replace_same_bytes(original_path(request, role))
        return result

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", changed)
    with pytest.raises(CandidateEvaluationError):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert_incomplete(request)


@pytest.mark.parametrize("relative", ["output/result.json", "inputs/value", "evaluator.py", "request.json"])
@pytest.mark.parametrize("same_bytes", [False, True])
def test_harness_snapshot_content_or_inode_drift_is_rejected(tmp_path, monkeypatch, relative, same_bytes):
    admission, request = fixture(tmp_path)
    process = evaluation._bounded_process_bytes

    def changed(*args, **kwargs):
        result = process(*args, **kwargs)
        path = Path(kwargs["cwd"]) / relative
        if same_bytes:
            replace_same_bytes(path)
        else:
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", changed)
    with pytest.raises(CandidateEvaluationError, match="snapshot_changed"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert_incomplete(request)


def test_optional_output_created_during_harness_changes_original_observation(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path, outputs=[
        {"path": "output/result.json", "format": "json", "fields": ["value"]},
        {"path": "output/optional/detail.txt", "format": "text", "required": False},
    ])
    process = evaluation._bounded_process_bytes

    def changed(*args, **kwargs):
        result = process(*args, **kwargs)
        path = request["workspace_path"] / "output/optional/detail.txt"
        path.parent.mkdir()
        path.write_text("appeared")
        return result

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", changed)
    with pytest.raises(CandidateEvaluationError, match="output_changed"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert_incomplete(request)


def test_unexpected_harness_file_is_preserved_without_publishing_evaluation(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    process = evaluation._bounded_process_bytes

    def changed(*args, **kwargs):
        result = process(*args, **kwargs)
        (Path(kwargs["cwd"]) / "foreign").write_bytes(b"retained")
        return result

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", changed)
    with pytest.raises(CandidateEvaluationError, match="snapshot_changed"):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert (assert_incomplete(request) / "foreign").read_bytes() == b"retained"


@pytest.mark.parametrize("relative", ["output/result.json", "inputs/value", "evaluator.py", "request.json", "report.json"])
def test_inspection_rejects_same_byte_replacement_of_each_bound_file(tmp_path, relative):
    admission, request = fixture(tmp_path)
    result = evaluation.evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path / relative
    replace_same_bytes(path)
    content = path.read_bytes()
    with pytest.raises(CandidateEvaluationError, match="snapshot_changed"):
        evaluation.inspect_candidate_evaluation(result.evaluation_path)
    assert path.read_bytes() == content


@pytest.mark.parametrize("relative", ["unexpected", "output/unexpected", "inputs/unexpected"])
def test_inspection_rejects_and_preserves_undeclared_nodes(tmp_path, relative):
    admission, request = fixture(tmp_path)
    result = evaluation.evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path / relative
    path.mkdir()
    with pytest.raises(CandidateEvaluationError, match="snapshot_changed"):
        evaluation.inspect_candidate_evaluation(result.evaluation_path)
    assert path.is_dir()


@pytest.mark.parametrize("field", ["size", "inode", "device"])
def test_manifest_file_descriptor_numbers_require_exact_integer_types(tmp_path, field):
    admission, request = fixture(tmp_path)
    result = evaluation.evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path / "evaluation.json"
    manifest = json.loads(path.read_bytes())
    descriptor = manifest["files"]["inputs/value"]
    descriptor[field] = True if field == "size" else float(descriptor[field])
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(CandidateEvaluationError):
        evaluation.inspect_candidate_evaluation(result.evaluation_path)


@pytest.mark.parametrize("validity", [True, 1.0])
def test_manifest_report_does_not_use_boolean_or_float_equality_for_validity(tmp_path, validity):
    admission, request = fixture(tmp_path)
    result = evaluation.evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path / "evaluation.json"
    manifest = json.loads(path.read_bytes())
    manifest["report"]["validity"] = validity
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(CandidateEvaluationError):
        evaluation.inspect_candidate_evaluation(result.evaluation_path)


def test_interruption_retains_private_snapshot_without_evaluation_manifest(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert_incomplete(request)


def retained_bytes(path):
    return {item.relative_to(path).as_posix(): item.read_bytes()
            for item in path.rglob("*") if item.is_file()}


def observe_harness_launches(monkeypatch):
    process = evaluation._bounded_process_bytes
    launches = []

    def observed(*args, **kwargs):
        launches.append(kwargs["cwd"])
        return process(*args, **kwargs)

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", observed)
    return launches


@pytest.mark.parametrize("relative", [
    "request.json", "evaluator.py", "output/result.json", "report.json", "evaluation.json",
])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_interrupted_record_writes_preserve_partial_bytes_without_accepting_score(
    tmp_path, monkeypatch, relative, failure,
):
    admission, request = fixture(tmp_path)
    launches = observe_harness_launches(monkeypatch)
    write_file = evaluation.PrivateTree.write
    write_bytes = os.write
    partial = []

    def faulted_write(tree, name, content):
        if name != relative:
            return write_file(tree, name, content)

        def fail_after_partial_write(descriptor, view):
            if partial:
                raise failure("injected write interruption")
            prefix = bytes(view[:max(1, len(view) // 2)])
            count = write_bytes(descriptor, prefix)
            partial.append(prefix[:count])
            return count

        with monkeypatch.context() as phase:
            phase.setattr(os, "write", fail_after_partial_write)
            return write_file(tree, name, content)

    monkeypatch.setattr(evaluation.PrivateTree, "write", faulted_write)
    expected_error = CandidateEvaluationError if failure is OSError else KeyboardInterrupt
    with pytest.raises(expected_error):
        evaluation.evaluate_candidate_execution(admission, **request)
    directories = list(request["evaluation_root"].iterdir())
    assert len(directories) == 1
    path = directories[0]
    assert (path / relative).read_bytes() == partial[0]
    before = retained_bytes(path)
    with pytest.raises(CandidateEvaluationError):
        evaluation.inspect_candidate_evaluation(path)
    assert retained_bytes(path) == before
    assert len(launches) == int(relative in {"report.json", "evaluation.json"})
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("boundary", ["snapshot", "before_report", "published"])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_sync_failures_preserve_inspectable_state_at_each_publication_boundary(
    tmp_path, monkeypatch, boundary, failure,
):
    admission, request = fixture(tmp_path)
    launches = observe_harness_launches(monkeypatch)
    sync = evaluation.PrivateTree.sync_and_check
    faults = []

    def faulted_sync(tree):
        stage = ("published" if ("evaluation.json",) in tree.files else
                 "before_report" if launches else "snapshot")
        if stage != boundary:
            return sync(tree)

        def interrupted_fsync(descriptor):
            faults.append(descriptor)
            raise failure("injected sync interruption")

        with monkeypatch.context() as phase:
            phase.setattr(os, "fsync", interrupted_fsync)
            return sync(tree)

    monkeypatch.setattr(evaluation.PrivateTree, "sync_and_check", faulted_sync)
    expected_error = CandidateEvaluationError if failure is OSError else KeyboardInterrupt
    with pytest.raises(expected_error):
        evaluation.evaluate_candidate_execution(admission, **request)
    assert len(faults) == 1
    directories = list(request["evaluation_root"].iterdir())
    assert len(directories) == 1
    path = directories[0]
    before = retained_bytes(path)
    if boundary == "published":
        result = evaluation.inspect_candidate_evaluation(path)
        assert result.report.validity == 1 and result.report.combined_score == 9
    else:
        with pytest.raises(CandidateEvaluationError, match="incomplete"):
            evaluation.inspect_candidate_evaluation(path)
    assert retained_bytes(path) == before
    assert len(launches) == int(boundary != "snapshot")
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_final_readback_failure_can_leave_complete_retained_evaluation(tmp_path, monkeypatch, failure):
    admission, request = fixture(tmp_path)
    launches = observe_harness_launches(monkeypatch)
    inspect = evaluation.inspect_candidate_evaluation
    faults = []

    def interrupted_readback(path, **kwargs):
        assert (path / "evaluation.json").is_file()
        faults.append(path)
        raise failure("injected final readback interruption")

    monkeypatch.setattr(evaluation, "inspect_candidate_evaluation", interrupted_readback)
    expected_error = CandidateEvaluationError if failure is OSError else KeyboardInterrupt
    with pytest.raises(expected_error):
        evaluation.evaluate_candidate_execution(admission, **request)
    directories = list(request["evaluation_root"].iterdir())
    assert directories == faults and len(directories) == 1
    before = retained_bytes(directories[0])
    result = inspect(directories[0])
    assert result.report.validity == 1 and result.report.combined_score == 9
    assert retained_bytes(directories[0]) == before
    assert len(launches) == 1
    assert (request["workspace_path"] / "count").read_text() == "x"
