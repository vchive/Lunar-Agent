"""A fixed bundle profile is bound to the complete normal solve input ledger."""
from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from test_bundle_population import build_context

from lunar_evolution.artifacts import ArtifactStore
from lunar_evolution.candidate_execution import CandidateExecutionInput
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import EvolutionError
from lunar_evolution.runtime import MockRuntime
from lunar_evolution.solve_bundle import (
    bundle_pipeline_sha256,
    prepare_solve_bundle_pipeline,
    validate_solve_bundle_inputs,
)


def _fixture(tmp_path):
    context = build_context(tmp_path / "profile")
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    parent = controller.create_conversational_run("Improve a bounded integer choice", workspace=tmp_path / "parent")
    task = controller.store.list_tasks(parent.id)[0]
    target = parent.workspace / "data/raw/value"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"10")
    ArtifactStore(parent.workspace, controller.store, parent.id).record(target, task.id, kind="input_data")
    return context.bundle_pipeline, controller.store, parent, task


def _record(store, parent, task, path, content, *, digest=None, size=None, kind="input_data"):
    target = parent.workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return store.add_artifact(
        parent.id, task.id, path, digest or hashlib.sha256(content).hexdigest(),
        len(content) if size is None else size, kind,
    )


def test_solve_profile_rebinds_parent_inputs_in_fresh_clone_without_ledger_writes(tmp_path):
    pipeline, store, parent, _ = _fixture(tmp_path)
    fingerprint = bundle_pipeline_sha256(pipeline)
    original_root = pipeline.input_root
    # The solve input ledger is authoritative even when the profile's original data differs.
    (original_root / "value").write_bytes(b"unrelated profile directory")
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    bound = prepare_solve_bundle_pipeline(store, parent.id, pipeline)

    assert bound is not pipeline
    assert bound.input_root == parent.workspace / "data/raw"
    assert pipeline.input_root == original_root
    assert bound.inputs == pipeline.inputs
    assert bundle_pipeline_sha256(bound) == fingerprint
    assert bound.runner_fingerprint == pipeline.runner_fingerprint
    assert bound.evaluator.digest() == pipeline.evaluator.digest()
    bound.preflight()
    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts
    assert not (parent.workspace / "evolution-run").exists()


def test_identical_duplicate_input_rows_are_unambiguous(tmp_path):
    pipeline, store, parent, task = _fixture(tmp_path)
    _record(store, parent, task, "data/raw/value", b"10")
    assert len([item for item in store.list_artifacts(parent.id) if item["kind"] == "input_data"]) == 2
    bound = prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    assert len(bound.inputs) == 1


@pytest.mark.parametrize("mismatch", ["missing_profile_input", "extra_profile_input", "conflicting_row", "stale_row"])
def test_complete_input_ledger_must_match_profile_exactly(tmp_path, mismatch):
    pipeline, store, parent, task = _fixture(tmp_path)
    if mismatch == "missing_profile_input":
        _record(store, parent, task, "data/raw/extra", b"20")
    elif mismatch == "extra_profile_input":
        pipeline.inputs = (*pipeline.inputs, CandidateExecutionInput("extra", "fixture", 2, hashlib.sha256(b"20").hexdigest()))
    elif mismatch == "conflicting_row":
        _record(store, parent, task, "data/raw/value", b"10", digest="e" * 64)
    else:
        # The newest row matches changed bytes; the old row must not silently disappear.
        _record(store, parent, task, "data/raw/value", b"11")
        pipeline.inputs = (CandidateExecutionInput("value", "fixture", 2, hashlib.sha256(b"11").hexdigest()),)
    before = store.list_events(parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    assert store.list_events(parent.id) == before
    assert not (parent.workspace / "evolution-run").exists()


@pytest.mark.parametrize("drift", ["bytes", "missing", "symlink", "directory_symlink", "harness"])
def test_parent_input_and_evaluator_byte_drift_is_not_rescued_by_original_profile_data(tmp_path, drift):
    pipeline, store, parent, _ = _fixture(tmp_path)
    target = parent.workspace / "data/raw/value"
    if drift == "bytes":
        target.write_bytes(b"11")
    elif drift == "missing":
        target.unlink()
    elif drift == "symlink":
        target.unlink()
        target.symlink_to(pipeline.input_root / "value")
    elif drift == "directory_symlink":
        target.unlink()
        target.parent.rmdir()
        (parent.workspace / "data/raw").symlink_to(pipeline.input_root, target_is_directory=True)
    else:
        pipeline.harness_path.write_bytes(b"changed private evaluator")
    before = store.list_events(parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    assert store.list_events(parent.id) == before


@pytest.mark.parametrize("field,value", [
    ("size", True), ("size", -1), ("sha256", "not-a-digest"),
    ("path", "value"), ("path", "data/raw/../value"),
])
def test_malformed_ledger_rows_fail_closed(tmp_path, monkeypatch, field, value):
    pipeline, store, parent, _ = _fixture(tmp_path)
    rows = store.list_artifacts(parent.id)
    rows[0][field] = value
    monkeypatch.setattr(store, "list_artifacts", lambda run_id: rows)
    with pytest.raises((EvolutionError, ValueError)):
        prepare_solve_bundle_pipeline(store, parent.id, pipeline)


def test_non_input_artifacts_and_unregistered_files_are_not_exposed_as_pipeline_inputs(tmp_path):
    pipeline, store, parent, task = _fixture(tmp_path)
    _record(store, parent, task, "data/raw/unregistered", b"private note", kind="note")
    (parent.workspace / "data/raw/not-in-ledger").write_bytes(b"not an input")
    bound = prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    assert [item.target for item in bound.inputs] == ["value"]


def test_semantic_profile_hash_ignores_storage_paths(tmp_path):
    pipeline, store, parent, _ = _fixture(tmp_path)
    expected = bundle_pipeline_sha256(pipeline)
    replacement = prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    other_harness = tmp_path / "relocated-evaluator.py"
    other_harness.write_bytes(pipeline.harness_path.read_bytes())
    replacement.harness_path = other_harness
    assert replacement.harness_path != pipeline.harness_path
    assert replacement.input_root != pipeline.input_root
    assert bundle_pipeline_sha256(replacement) == expected


@pytest.mark.parametrize("field", ["command", "environment", "timeout_seconds", "max_output_bytes", "inputs", "evaluator", "dependency_sha256", "environment_sha256"])
def test_semantic_profile_hash_binds_every_execution_and_evaluation_setting(tmp_path, field):
    pipeline, _, _, _ = _fixture(tmp_path)
    original = bundle_pipeline_sha256(pipeline)
    if field == "command":
        pipeline.command = (*pipeline.command, "-I")
    elif field == "environment":
        pipeline.environment = (("PYTHONHASHSEED", "1"),)
    elif field == "timeout_seconds":
        pipeline.timeout_seconds += 1
    elif field == "max_output_bytes":
        pipeline.max_output_bytes += 1
    elif field == "inputs":
        pipeline.inputs = (replace(pipeline.inputs[0], source_label="changed"),)
    elif field == "evaluator":
        pipeline.evaluator = replace(pipeline.evaluator, timeout_seconds=4)
    else:
        setattr(pipeline, field, "f" * 64)
    assert bundle_pipeline_sha256(pipeline) != original


def test_unknown_parent_cannot_be_rebound(tmp_path):
    pipeline, store, _, _ = _fixture(tmp_path)
    with pytest.raises((EvolutionError, ValueError)):
        prepare_solve_bundle_pipeline(store, "missing-parent", pipeline)


def test_scored_snapshot_accepts_identical_duplicate_input_rows_without_writes(tmp_path):
    _, store, parent, task = _fixture(tmp_path)
    _record(store, parent, task, "data/raw/value", b"10")
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    validate_solve_bundle_inputs(store, parent.id, {"value": b"10"})

    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts


@pytest.mark.parametrize("snapshot", [{}, {"value": b"10", "extra": b"20"}, {"value": b"11"}])
def test_scored_snapshot_must_match_complete_parent_input_ledger(tmp_path, snapshot):
    _, store, parent, _ = _fixture(tmp_path)
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    with pytest.raises(EvolutionError, match="^solve_bundle_profile_invalid$"):
        validate_solve_bundle_inputs(store, parent.id, snapshot)

    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts


@pytest.mark.parametrize("drift", ["bytes", "symlink"])
def test_scored_snapshot_validates_current_parent_bytes_after_ledger_match(tmp_path, drift):
    pipeline, store, parent, _ = _fixture(tmp_path)
    target = parent.workspace / "data/raw/value"
    if drift == "bytes":
        target.write_bytes(b"11")
    else:
        target.unlink()
        target.symlink_to(pipeline.input_root / "value")
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    with pytest.raises(EvolutionError, match="^solve_bundle_profile_invalid$"):
        validate_solve_bundle_inputs(store, parent.id, {"value": b"10"})

    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts


@pytest.mark.parametrize("layout", ["fresh", "workspace_only", "data_only", "empty_raw"])
def test_empty_input_profile_and_snapshot_accept_absent_staging_without_creating_it(tmp_path, layout):
    pipeline = build_context(tmp_path / "profile").bundle_pipeline
    pipeline.inputs = ()
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    store = controller.store
    parent = controller.create_conversational_run("Solve without input files", workspace=tmp_path / "parent")
    paths = (parent.workspace, parent.workspace / "data", parent.workspace / "data/raw")
    if layout != "fresh":
        paths[["workspace_only", "data_only", "empty_raw"].index(layout)].mkdir(parents=True)
    before = tuple(path.exists() for path in paths)
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    bound = prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    validate_solve_bundle_inputs(store, parent.id, {})

    assert bound.inputs == ()
    assert bound.input_root == parent.workspace / "data/raw"
    assert bundle_pipeline_sha256(bound) == bundle_pipeline_sha256(pipeline)
    assert tuple(path.exists() for path in paths) == before
    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts


@pytest.mark.parametrize("link", ["workspace", "data", "raw"])
def test_empty_input_profile_and_snapshot_reject_existing_directory_symlinks(tmp_path, link):
    pipeline = build_context(tmp_path / "profile").bundle_pipeline
    pipeline.inputs = ()
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    store = controller.store
    parent = controller.create_conversational_run("Solve without input files", workspace=tmp_path / "parent")
    outside = tmp_path / "outside"
    outside.mkdir()
    relative = {"workspace": "", "data": "data", "raw": "data/raw"}[link]
    target = parent.workspace / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    events, artifacts = store.list_events(parent.id), store.list_artifacts(parent.id)

    with pytest.raises(EvolutionError, match="^solve_bundle_profile_invalid$"):
        prepare_solve_bundle_pipeline(store, parent.id, pipeline)
    with pytest.raises(EvolutionError, match="^solve_bundle_profile_invalid$"):
        validate_solve_bundle_inputs(store, parent.id, {})

    assert target.is_symlink()
    assert store.list_events(parent.id) == events
    assert store.list_artifacts(parent.id) == artifacts
