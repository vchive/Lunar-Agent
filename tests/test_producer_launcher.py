from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import (
    ProducerLaunchError,
    build_producer_launch_attestation,
    build_producer_launch_intent,
    parse_producer_launch_intent,
    preflight_producer_launch,
    verify_producer_launch_attestation,
)

DIGEST = "a" * 64


def _intent(tmp_path: Path):
    root = tmp_path / "producer-root"
    root.mkdir()
    executable = root / "producer.bin"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return root, build_producer_launch_intent(
        producer_root=root,
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        contract_sha256=DIGEST,
        evaluator_kind="local",
        evaluator_fingerprint=DIGEST,
        runner_fingerprint=DIGEST,
        generator_fingerprint=DIGEST,
        dependency_sha256=DIGEST,
        environment_sha256=DIGEST,
        producer_id="producer-001",
        producer_fingerprint=DIGEST,
        executable_relative="producer.bin",
        argv=("producer.bin", "-V"),
        working_directory="work",
        output_directory="output",
        request_timeout_seconds=10,
        max_requests=2,
        output_max_bytes=1024,
        wall_timeout_seconds=20,
    )


def test_intent_round_trip_and_attestation(tmp_path: Path):
    root, intent = _intent(tmp_path)
    assert intent.intent_sha256 == intent.digest()
    assert parse_producer_launch_intent(intent.to_dict()).digest() == intent.digest()
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    verify_producer_launch_attestation(intent, attestation)

    admission = preflight_producer_launch(tmp_path, intent, producer_root=root, candidate_integrity_authority={
        "schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local", "evaluator_fingerprint": DIGEST,
        "dependency_sha256": DIGEST, "environment_sha256": DIGEST, "runner_fingerprint": DIGEST,
        "generator_fingerprint": DIGEST,
    }, expected_run_id="run-001", expected_parent_task_id="parent-001", expected_task_id="task-001")
    assert admission.status == "preflight_passed"
    assert admission.registration_attestation_required is True
    assert admission.derived_output_directory == "evolution/producer-batches/journal-001/output"


def test_preflight_is_zero_write_and_rejects_executable_drift(tmp_path: Path):
    root, intent = _intent(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    kwargs = {"candidate_integrity_authority": {
        "schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local", "evaluator_fingerprint": DIGEST,
        "dependency_sha256": DIGEST, "environment_sha256": DIGEST, "runner_fingerprint": DIGEST,
        "generator_fingerprint": DIGEST,
    }, "expected_run_id": "run-001", "expected_parent_task_id": "parent-001", "expected_task_id": "task-001"}
    preflight_producer_launch(tmp_path, intent, producer_root=root, **kwargs)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after

    (root / "producer.bin").write_bytes(b"changed")
    with pytest.raises(ProducerLaunchError) as exc:
        preflight_producer_launch(tmp_path, intent, producer_root=root, **kwargs)
    assert exc.value.code == "producer_launch_executable_changed"


def test_intent_rejects_shell_and_unknown_or_duplicate_fields(tmp_path: Path):
    _root, intent = _intent(tmp_path)
    value = intent.to_dict()
    value["argv"] = ["/bin/sh", "-c", "echo unsafe"]
    with pytest.raises(ProducerLaunchError) as exc:
        parse_producer_launch_intent(value)
    assert exc.value.code == "producer_launch_shell_unsupported"

    encoded = json.dumps(intent.to_dict(), separators=(",", ":"))[:-1] + ',"extra":1}'
    with pytest.raises(ProducerLaunchError) as exc:
        parse_producer_launch_intent(encoded)
    assert exc.value.code == "producer_launch_schema_invalid"


def test_attestation_tuple_is_exact(tmp_path: Path):
    _root, intent = _intent(tmp_path)
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    tampered = type(attestation)(**{**attestation.to_dict(), "task_id": "other-task"})
    with pytest.raises(ProducerLaunchError) as exc:
        verify_producer_launch_attestation(intent, tampered)
    assert exc.value.code == "producer_launch_attestation_mismatch"


def test_preflight_compares_authority_and_identity(tmp_path: Path):
    root, intent = _intent(tmp_path)

    authority = {"schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local", "evaluator_fingerprint": DIGEST,
                 "dependency_sha256": DIGEST, "environment_sha256": DIGEST, "runner_fingerprint": DIGEST,
                 "generator_fingerprint": DIGEST}
    preflight_producer_launch(tmp_path, intent, producer_root=root, candidate_integrity_authority=authority,
                              expected_run_id="run-001", expected_parent_task_id="parent-001", expected_task_id="task-001")
    with pytest.raises(ProducerLaunchError) as exc:
        preflight_producer_launch(tmp_path, intent, producer_root=root, candidate_integrity_authority=authority,
                                  expected_run_id="wrong", expected_parent_task_id="parent-001", expected_task_id="task-001")
    assert exc.value.code == "producer_launch_identity_mismatch"


def test_prelaunch_intent_does_not_require_future_plan_or_journal(tmp_path: Path):
    root, intent = _intent(tmp_path)
    value = intent.to_dict()
    value["intent_sha256"] = None
    pending = parse_producer_launch_intent(value)
    assert "admission_sha256" not in pending.to_dict()
    admission = preflight_producer_launch(tmp_path, pending, producer_root=root,
        candidate_integrity_authority={"schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local", "evaluator_fingerprint": DIGEST,
            "dependency_sha256": DIGEST, "environment_sha256": DIGEST, "runner_fingerprint": DIGEST, "generator_fingerprint": DIGEST},
        expected_run_id="run-001", expected_parent_task_id="parent-001", expected_task_id="task-001")
    assert admission.status == "preflight_passed"


def test_symlinked_executable_parent_is_rejected(tmp_path: Path):
    root, intent = _intent(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    (nested / "producer.bin").write_bytes((root / "producer.bin").read_bytes())
    (nested / "producer.bin").chmod(0o755)
    link_root = tmp_path / "link-root"
    link_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(ProducerLaunchError) as exc:
        preflight_producer_launch(
            tmp_path, intent, producer_root=link_root,
            candidate_integrity_authority={"schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local",
                "evaluator_fingerprint": DIGEST, "dependency_sha256": DIGEST,
                "environment_sha256": DIGEST, "runner_fingerprint": DIGEST,
                "generator_fingerprint": DIGEST}, expected_run_id="run-001",
            expected_parent_task_id="parent-001", expected_task_id="task-001",
        )
    assert exc.value.code == "producer_launch_workspace_invalid" or exc.value.code == "producer_launch_executable_invalid"


def test_broken_output_ancestor_is_rejected(tmp_path: Path):
    root, intent = _intent(tmp_path)
    workspace = tmp_path / "evolution"
    workspace.mkdir()
    (workspace / "producer-batches").mkdir()
    (workspace / "producer-batches" / intent.journal_id).symlink_to(tmp_path / "missing-target")
    authority = {
        "schema_version": "1", "contract_sha256": DIGEST, "evaluator_kind": "local", "evaluator_fingerprint": DIGEST,
        "dependency_sha256": DIGEST, "environment_sha256": DIGEST, "runner_fingerprint": DIGEST,
        "generator_fingerprint": DIGEST,
    }
    with pytest.raises(ProducerLaunchError) as exc:
        preflight_producer_launch(
            tmp_path, intent, producer_root=root, candidate_integrity_authority=authority,
            expected_run_id="run-001", expected_parent_task_id="parent-001", expected_task_id="task-001",
        )
    assert exc.value.code == "producer_launch_output_invalid"
