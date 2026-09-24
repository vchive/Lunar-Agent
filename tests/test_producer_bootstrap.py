from __future__ import annotations

import json

import pytest

from lunar_evolution.producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    TrustedBootstrapSession,
    parse_bootstrap_handshake_frame,
)

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
