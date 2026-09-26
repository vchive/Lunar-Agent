from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from lunar_evolution.producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapEvidence,
    TrustedBootstrapLaunch,
    TrustedBootstrapRegistration,
    TrustedBootstrapSession,
    build_trusted_bootstrap_launch,
    build_trusted_bootstrap_registration,
    parse_bootstrap_handshake_frame,
    parse_trusted_bootstrap_evidence,
    parse_trusted_bootstrap_registration,
    verify_trusted_bootstrap_process_registration,
    verify_trusted_bootstrap_registration,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.producer_process import PRODUCER_PROCESS_PROTOCOL

DIGEST = "a" * 64


def _descriptor() -> TrustedBootstrapDescriptor:
    return TrustedBootstrapDescriptor(
        implementation_version="bootstrap-1",
        bootstrap_sha256=DIGEST,
        size=128,
        device=1,
        inode=2,
        mtime_ns=3,
        ctime_ns=4,
        allowlist_id="local-bootstrap",
        platform_execution_mode="fixture-only",
    )


def _launch() -> TrustedBootstrapLaunch:
    return TrustedBootstrapLaunch(
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        intent_sha256=DIGEST,
        attestation_sha256=DIGEST,
        bootstrap_descriptor_sha256=_descriptor().descriptor_sha256 or _descriptor().digest(),
        target_executable_identity="b" * 64,
        gate_protocol="fd-read-one-byte-v1",
        gate_nonce="nonce-001",
    )


def _producer_admission(tmp_path: Path):
    root = tmp_path / "producer-root"
    root.mkdir()
    executable = root / "producer.py"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    executable.chmod(0o755)
    intent = build_producer_launch_intent(
        producer_root=root, launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", contract_sha256=DIGEST,
        evaluator_kind="local", evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST,
        generator_fingerprint=DIGEST, dependency_sha256=DIGEST, environment_sha256=DIGEST,
        producer_id="fixture", producer_fingerprint=DIGEST, executable_relative="producer.py",
        argv=("producer.py",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024, wall_timeout_seconds=1,
    )
    return intent, build_producer_launch_attestation(intent, "nonce-001")


def _production_descriptor() -> TrustedBootstrapDescriptor:
    return TrustedBootstrapDescriptor(
        implementation_version="bootstrap-1", bootstrap_sha256=DIGEST, size=128,
        device=1, inode=2, mtime_ns=3, ctime_ns=4, allowlist_id="local-bootstrap",
        platform_execution_mode="darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound",
    )


def _formal_registration() -> tuple[TrustedBootstrapLaunch, TrustedBootstrapDescriptor, dict[str, object]]:
    descriptor = _production_descriptor()
    launch_fields = _launch().to_dict(include_digest=False)
    launch_fields["bootstrap_descriptor_sha256"] = descriptor.descriptor_sha256
    launch = TrustedBootstrapLaunch(**launch_fields)
    owner = (
        {"kind": "darwin-libproc-starttime-v1", "pid": 1234, "start_sec": 42, "start_usec": 3}
        if sys.platform == "darwin" else
        {"kind": "linux-proc-starttime-v1", "pid": 1234, "boot_id": "boot-id", "starttime_ticks": 42}
    )
    identity = {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }
    registration: dict[str, object] = {
        "schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL,
        "launch_id": launch.launch_id, "journal_id": launch.journal_id,
        "run_id": launch.run_id, "parent_task_id": launch.parent_task_id,
        "task_id": launch.task_id, "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "consumption_sha256": "c" * 64,
        "executable_identity": _test_digest(identity),
        "owner_identity": owner, "owner_identity_sha256": _test_digest(owner),
        "execution_binding": (
            "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
        ),
        "execution_snapshot_relative_path": (
            ".producer-snapshots/executable" if sys.platform == "darwin" else None
        ),
        "execution_snapshot_sha256": descriptor.bootstrap_sha256,
        "execution_snapshot_size": descriptor.size,
        "pid": 1234, "pgid": 1234,
        "recovery_lock_protocol": "journal-flock-v1",
        "recovery_lock_device": 5, "recovery_lock_inode": 6,
        "gate_protocol": launch.gate_protocol, "registered_at_unix_ns": 7,
        "launch_sha256": launch.launch_sha256,
        "bootstrap_descriptor_sha256": descriptor.descriptor_sha256,
        "target_executable_identity": launch.target_executable_identity,
    }
    registration["registration_sha256"] = _test_digest(registration)
    return launch, descriptor, registration


def _test_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_formal_registration_binds_bootstrap_target_and_feature156_owner_lock():
    launch, descriptor, registration = _formal_registration()
    assert verify_trusted_bootstrap_process_registration(launch, descriptor, registration) == registration
    encoded = json.dumps(registration, sort_keys=True, separators=(",", ":"))
    assert verify_trusted_bootstrap_process_registration(launch, descriptor, encoded) == registration


@pytest.mark.parametrize(
    ("field", "replacement", "code"),
    [
        ("launch_sha256", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("bootstrap_descriptor_sha256", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("target_executable_identity", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("task_id", "other-task", "producer_bootstrap_process_registration_binding_mismatch"),
        ("pid", 1235, "producer_bootstrap_process_registration_process_identity_invalid"),
        ("pgid", 1235, "producer_bootstrap_process_registration_process_identity_invalid"),
        ("owner_identity_sha256", "d" * 64, "producer_bootstrap_process_registration_owner_identity_invalid"),
        ("recovery_lock_inode", 0, "producer_bootstrap_process_registration_lock_identity_invalid"),
        ("execution_snapshot_sha256", "d" * 64, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("execution_snapshot_size", 129, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("executable_identity", "d" * 64, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("execution_binding", "pathname_unbound", "producer_bootstrap_process_registration_execution_binding_mismatch"),
    ],
)
def test_formal_registration_rejects_rehashed_identity_drift(field, replacement, code):
    launch, descriptor, registration = _formal_registration()
    registration[field] = replacement
    registration["registration_sha256"] = _test_digest({
        key: value for key, value in registration.items() if key != "registration_sha256"
    })
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == code


def test_formal_registration_rejects_owner_drift_even_with_rehashed_owner():
    launch, descriptor, registration = _formal_registration()
    owner = dict(registration["owner_identity"])
    owner["pid"] = 1235
    registration["owner_identity"] = owner
    registration["owner_identity_sha256"] = _test_digest(owner)
    registration["registration_sha256"] = _test_digest({
        key: value for key, value in registration.items() if key != "registration_sha256"
    })
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == "producer_bootstrap_process_registration_owner_identity_invalid"


def test_formal_registration_rejects_fixture_descriptor_and_tampered_self_digest():
    launch, descriptor, registration = _formal_registration()
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, _descriptor(), registration)
    assert exc.value.code == "producer_bootstrap_production_mode_required"

    registration["registered_at_unix_ns"] = 8
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == "producer_bootstrap_process_registration_digest_mismatch"


def test_formal_registration_rejects_missing_fields_and_noncanonical_encoding():
    launch, descriptor, registration = _formal_registration()
    missing = dict(registration)
    del missing["recovery_lock_device"]
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, missing)
    assert exc.value.code == "producer_bootstrap_process_registration_schema_invalid"

    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, json.dumps(registration, indent=2))
    assert exc.value.code == "producer_bootstrap_process_registration_noncanonical"


def test_launch_adapter_rejects_fixture_only_mode(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, attestation, _descriptor(), gate_nonce="nonce-001")
    assert exc.value.code == "producer_bootstrap_production_mode_required"


def test_launch_adapter_binds_verified_intent_and_attestation(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    launch = build_trusted_bootstrap_launch(
        intent, attestation, _production_descriptor(), gate_nonce="nonce-001",
    )
    assert launch.intent_sha256 == intent.intent_sha256
    assert launch.attestation_sha256 == attestation.attestation_sha256
    assert launch.target_executable_identity == intent.executable_sha256


def test_launch_adapter_rejects_attestation_drift(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    forged = dict(attestation.to_dict())
    forged["intent_sha256"] = "b" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, forged, _production_descriptor(), gate_nonce="nonce-001")
    assert exc.value.code == "producer_bootstrap_launch_attestation_invalid"


def test_launch_adapter_rejects_gate_nonce_drift(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, attestation, _production_descriptor(), gate_nonce="nonce-002")
    assert exc.value.code == "producer_bootstrap_gate_nonce_mismatch"


def _ready(launch: TrustedBootstrapLaunch) -> BootstrapHandshakeFrame:
    return BootstrapHandshakeFrame(
        sequence=1,
        kind="bootstrap_ready",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )


def _started(launch: TrustedBootstrapLaunch) -> BootstrapHandshakeFrame:
    return BootstrapHandshakeFrame(
        sequence=2,
        kind="target_started",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
        target_executable_identity=launch.target_executable_identity,
        observed_pid=1234,
        observed_pgid=1234,
    )


def test_descriptor_and_launch_have_stable_self_digests():
    descriptor = _descriptor()
    launch = _launch()
    assert descriptor.descriptor_sha256 == descriptor.digest()
    assert launch.launch_sha256 == launch.digest()


def test_registration_binds_launch_and_process_identity_with_stable_digest():
    launch = _launch()
    registration = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234)
    assert isinstance(registration, TrustedBootstrapRegistration)
    assert registration.registration_sha256 == registration.digest()
    assert verify_trusted_bootstrap_registration(launch, registration.to_dict()) == registration

    encoded = json.dumps(registration.to_dict(), sort_keys=True, separators=(",", ":"))
    assert parse_trusted_bootstrap_registration(encoded, launch=launch) == registration


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("launch_id", "producer_bootstrap_registration_binding_mismatch"),
        ("intent_sha256", "producer_bootstrap_registration_binding_mismatch"),
        ("bootstrap_descriptor_sha256", "producer_bootstrap_registration_binding_mismatch"),
        ("target_executable_identity", "producer_bootstrap_registration_binding_mismatch"),
    ],
)
def test_registration_rejects_launch_identity_drift(field: str, code: str):
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value[field] = "d" * 64 if field.endswith("sha256") or field == "target_executable_identity" else "other-launch"
    value["registration_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_registration(launch, value)
    assert exc.value.code == code


def test_registration_rejects_noncanonical_or_digest_tampering():
    launch = _launch()
    registration = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234)
    encoded = json.dumps(registration.to_dict(), indent=2)
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(encoded)
    assert exc.value.code == "producer_bootstrap_registration_noncanonical"

    forged = registration.to_dict()
    forged["pid"] = 4321
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(forged)
    assert exc.value.code == "producer_bootstrap_registration_digest_mismatch"


@pytest.mark.parametrize("field", ["pid", "pgid"])
def test_registration_rejects_invalid_process_identity(field: str):
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value[field] = True
    value["registration_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(value)
    assert exc.value.code == "producer_bootstrap_registration_process_identity_invalid"


def test_trusted_bootstrap_happy_path_produces_passed_evidence():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    assert session.evidence().status == "unknown"
    session.record_eof()
    evidence = session.evidence()
    assert evidence.status == "passed"
    assert evidence.release_observed is True
    assert evidence.target_start_count == 1
    assert evidence.evidence_sha256 == evidence.digest()


def test_evidence_parser_requires_canonical_self_authenticating_payload():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    session.record_eof()
    evidence = session.evidence()

    encoded = json.dumps(evidence.to_dict(), sort_keys=True, separators=(",", ":"))
    assert parse_trusted_bootstrap_evidence(encoded) == evidence

    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(json.dumps(evidence.to_dict(), indent=2))
    assert exc.value.code == "producer_bootstrap_evidence_noncanonical"

    forged = evidence.to_dict()
    forged["target_group_identity"] = "d" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(forged)
    assert exc.value.code == "producer_bootstrap_digest_mismatch"

    forged["evidence_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(forged)
    assert exc.value.code == "producer_bootstrap_evidence_digest_invalid"
    assert TrustedBootstrapEvidence(**forged).evidence_sha256 is not None


def test_registration_parser_rejects_missing_digest_for_persisted_payload():
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value["registration_sha256"] = None

    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(value, launch=launch)
    assert exc.value.code == "producer_bootstrap_registration_digest_invalid"


def test_terminal_frame_after_target_start_keeps_passed_evidence():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    terminal = BootstrapHandshakeFrame(
        sequence=3,
        kind="terminal",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )
    session.accept_frame(terminal)
    evidence = session.evidence()
    assert evidence.status == "passed"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is True
    with pytest.raises(ProducerBootstrapError) as exc:
        session.release("nonce-001")
    assert exc.value.code == "producer_bootstrap_terminal"
    assert session.evidence().status == "passed"


def test_terminal_frame_before_target_start_is_failed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    terminal = BootstrapHandshakeFrame(
        sequence=3,
        kind="terminal",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(terminal)
    assert exc.value.code == "producer_bootstrap_terminal_order_invalid"
    evidence = session.evidence()
    assert evidence.status == "failed"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is False


@pytest.mark.parametrize(
    ("action", "code"),
    [
        ("wrong_token", "producer_bootstrap_release_token_invalid"),
        ("duplicate_release", "producer_bootstrap_duplicate_release"),
        ("early_target", "producer_bootstrap_target_started_before_release"),
        ("pre_gate_work", "producer_bootstrap_pre_gate_work"),
    ],
)
def test_invalid_order_is_terminal_and_never_passes(action: str, code: str):
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        if action == "wrong_token":
            session.release("wrong")
        elif action == "duplicate_release":
            session.release("nonce-001")
            session.release("nonce-001")
        elif action == "early_target":
            session.accept_frame(_started(launch))
        else:
            session.record_pre_gate_target_work()
    assert exc.value.code == code
    assert session.evidence().status == "failed"


def test_duplicate_target_start_and_identity_drift_fail_closed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(_started(launch))
    assert exc.value.code == "producer_bootstrap_duplicate_target_start"

    other = TrustedBootstrapSession(launch, "c" * 64)
    other.accept_frame(_ready(launch))
    other.release("nonce-001")
    altered = _started(launch).to_dict()
    altered["target_executable_identity"] = "d" * 64
    altered["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        other.accept_frame(parse_bootstrap_handshake_frame(altered))
    assert exc.value.code == "producer_bootstrap_target_identity_mismatch"


def test_frame_parser_rejects_duplicate_keys_and_tampering():
    launch = _launch()
    frame = _ready(launch).to_dict()
    duplicate = json.dumps(frame).replace('"kind": "bootstrap_ready"', '"kind": "bootstrap_ready", "kind": "bootstrap_ready"')
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(duplicate)
    assert exc.value.code == "producer_bootstrap_duplicate_key"

    frame["intent_sha256"] = "e" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(frame)
    assert exc.value.code == "producer_bootstrap_digest_mismatch"


def test_session_malformed_or_unbound_frame_is_failed_not_unknown():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame('{"kind":"bootstrap_ready"}')
    assert exc.value.code == "producer_bootstrap_frame_schema_invalid"
    assert session.evidence().status == "failed"

    other = TrustedBootstrapSession(launch, "c" * 64)
    unbound = _ready(launch).to_dict()
    unbound["launch_sha256"] = "d" * 64
    unbound["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        other.accept_frame(unbound)
    assert exc.value.code == "producer_bootstrap_frame_binding_mismatch"
    assert other.evidence().status == "failed"


def test_ready_without_release_is_unknown_and_does_not_claim_success():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    evidence = session.evidence()
    assert evidence.status == "unknown"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is False


def test_early_target_failure_does_not_claim_ready_observed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(_started(launch))
    assert exc.value.code == "producer_bootstrap_target_started_before_release"
    evidence = session.evidence()
    assert evidence.status == "failed"
    assert evidence.bootstrap_ready_observed is False


def test_eof_before_target_start_is_terminal_failure():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        session.record_eof()
    assert exc.value.code == "producer_bootstrap_early_eof"
    assert session.evidence().status == "failed"


def test_eof_after_target_start_is_successful_handshake_close():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    assert session.evidence().status == "unknown"
    session.record_eof()
    assert session.evidence().status == "passed"


def test_non_target_frames_cannot_carry_process_identity():
    launch = _launch()
    frame = _ready(launch).to_dict()
    frame["observed_pid"] = 1234
    frame["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(frame)
    assert exc.value.code == "producer_bootstrap_target_frame_invalid"
