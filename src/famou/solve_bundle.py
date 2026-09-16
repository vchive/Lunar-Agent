"""Bind an explicit bundle profile to the inputs of a conversational parent run."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ._benchmark_files import absolute_path, read_regular_file
from ._candidate_workspace_io import DirectoryChain
from .bundle_evolution import MultiFileCandidatePipeline
from .candidate_evaluation_spec import canonical_json
from .candidate_execution import CandidateExecutionInput, _inputs
from .evolution import EvolutionError

if TYPE_CHECKING:
    from .store import Store


def _fail() -> None:
    raise EvolutionError("solve_bundle_profile_invalid")


def _clone(pipeline: MultiFileCandidatePipeline, *, input_root=None) -> MultiFileCandidatePipeline:
    if not isinstance(pipeline, MultiFileCandidatePipeline):
        _fail()
    return MultiFileCandidatePipeline(
        evaluator=pipeline.evaluator, harness_path=pipeline.harness_path,
        input_root=pipeline.input_root if input_root is None else input_root,
        inputs=pipeline.inputs, command=pipeline.command, environment=pipeline.environment,
        timeout_seconds=pipeline.timeout_seconds, max_output_bytes=pipeline.max_output_bytes,
        dependency_sha256=pipeline.dependency_sha256, environment_sha256=pipeline.environment_sha256,
    )


def bundle_pipeline_sha256(pipeline: MultiFileCandidatePipeline) -> str:
    """Hash semantic settings without persisting profile/harness/input storage locations."""
    try:
        value = _clone(pipeline)
        payload = {
            "protocol": "lunar-solve-bundle-profile-v1",
            "evaluator": value.evaluator.to_dict(), "inputs": [item.to_dict() for item in value.inputs],
            "command": list(value.command), "environment": dict(value.environment),
            "timeout_seconds": value.timeout_seconds, "max_output_bytes": value.max_output_bytes,
            "dependency_sha256": value.dependency_sha256, "environment_sha256": value.environment_sha256,
        }
        return hashlib.sha256(canonical_json(payload, maximum=128 * 1024)).hexdigest()
    except (AttributeError, OSError, TypeError, ValueError, RecursionError):
        _fail()


def _input_ledger(store: Store, parent_id: str, expected: dict) -> dict:
    observed = {}
    for row in store.list_artifacts(parent_id):
        if row.get("kind") != "input_data":
            continue
        path, size, digest = row.get("path"), row.get("size"), row.get("sha256")
        if (not isinstance(path, str) or path not in expected or type(size) is not int
                or size < 0 or not isinstance(digest, str) or (size, digest) != expected[path]
                or row.get("run_id", parent_id) != parent_id):
            _fail()
        observed[path] = (size, digest)
    if observed != expected:
        _fail()
    return observed


def _input_chain(root, *, required: bool) -> DirectoryChain:
    # An input-free intake has not created its workspace yet. Validate the existing
    # ancestor without requiring or creating unused data directories.
    if not required:
        while not root.exists() and not root.is_symlink():
            root = root.parent
    return DirectoryChain(root, "solve_bundle_profile_invalid")


def prepare_solve_bundle_pipeline(
    store: Store, parent_id: str, pipeline: MultiFileCandidatePipeline,
) -> MultiFileCandidatePipeline:
    """Return a fresh profile reading exactly the parent's ledger-bound staged input bytes.

    This is read-only. Source labels do not change target names: a profile target ``foo.csv``
    must correspond to ``data/raw/foo.csv`` in the parent input ledger. Identical duplicate
    rows are allowed, while stale/missing/extra declarations are rejected.
    """
    try:
        parent = store.get_run(parent_id)
        if parent is None or getattr(parent.status, "value", parent.status) == "cancelled":
            _fail()
        root = absolute_path(parent.workspace)
        bound = _clone(pipeline, input_root=root / "data" / "raw")
        expected = {"data/raw/" + item.target: (item.size, item.sha256) for item in bound.inputs}
        before = _input_ledger(store, parent_id, expected)
        chain = _input_chain(bound.input_root, required=bool(expected))
        try:
            bound.preflight()
            if before != _input_ledger(store, parent_id, expected):
                _fail()
            chain.check()
            _input_chain(bound.input_root, required=bool(expected)).close()
        finally:
            chain.close()
        if bundle_pipeline_sha256(bound) != bundle_pipeline_sha256(pipeline):
            _fail()
        return bound
    except (AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError):
        _fail()


def validate_solve_bundle_inputs(
    store: Store, parent_id: str, input_files: Mapping[str, bytes],
) -> None:
    """Verify selected evaluation-snapshot inputs against the complete parent input ledger."""
    try:
        if (not isinstance(input_files, Mapping) or len(input_files) > 64
                or any(not isinstance(value, bytes) for value in input_files.values())
                or sum(map(len, input_files.values())) > 16 * 1024 * 1024):
            _fail()
        descriptors = _inputs(tuple(
            CandidateExecutionInput(target, "scored_snapshot", len(content), hashlib.sha256(content).hexdigest())
            for target, content in input_files.items()
        ))
        expected = {"data/raw/" + item.target: (item.size, item.sha256) for item in descriptors}
        parent = store.get_run(parent_id)
        if parent is None or getattr(parent.status, "value", parent.status) == "cancelled":
            _fail()
        before = _input_ledger(store, parent_id, expected)
        root = absolute_path(parent.workspace) / "data" / "raw"
        chain = _input_chain(root, required=bool(expected))
        try:
            for item in descriptors:
                if read_regular_file(root / item.target, item.size) != input_files[item.target]:
                    _fail()
            if before != _input_ledger(store, parent_id, expected):
                _fail()
            chain.check()
            _input_chain(root, required=bool(expected)).close()
        finally:
            chain.close()
    except (AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError):
        _fail()
