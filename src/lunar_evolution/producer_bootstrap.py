"""Provider-free trusted producer bootstrap handshake.

This module models the ordering boundary for a future Lunar-owned bootstrap runtime.  It does
not spawn a producer.  The state machine accepts only bounded, canonical handshake frames and
keeps a cooperative declaration separate from a trusted bootstrap observation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

TRUSTED_BOOTSTRAP_PROTOCOL = "lunar-trusted-producer-bootstrap-v1"
TRUSTED_BOOTSTRAP_SCHEMA_VERSION = "1"
MAX_BOOTSTRAP_PAYLOAD_BYTES = 64 * 1024
MAX_BOOTSTRAP_SEQUENCE = 4
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_KINDS = frozenset({"bootstrap_ready", "target_started", "target_start_failed", "terminal"})
_STATUSES = frozenset({"passed", "failed", "unknown"})


class ProducerBootstrapError(ValueError):
    """Fixed-code bootstrap protocol failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBootstrapError(code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_canonical_invalid") from exc
    if len(encoded) > MAX_BOOTSTRAP_PAYLOAD_BYTES:
        _fail("producer_bootstrap_payload_too_large")
    return encoded


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in items:
        if key in result:
            _fail("producer_bootstrap_duplicate_key")
        result[key] = item
    return result


def _strict_json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProducerBootstrapError("producer_bootstrap_json_invalid") from exc
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_BOOTSTRAP_PAYLOAD_BYTES:
        _fail("producer_bootstrap_json_invalid")
    try:
        return json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: _fail("producer_bootstrap_json_invalid"))
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_json_invalid") from exc


def _object(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _id(value: object, code: str = "producer_bootstrap_identity_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str = "producer_bootstrap_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _int(value: object, *, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(code)
    return value


_DESCRIPTOR_FIELDS = frozenset({
    "schema_version", "protocol", "implementation_version", "bootstrap_sha256", "size",
    "device", "inode", "mtime_ns", "ctime_ns", "allowlist_id", "platform_execution_mode",
    "descriptor_sha256",
})


@dataclass(frozen=True, slots=True)
class TrustedBootstrapDescriptor:
    implementation_version: str
    bootstrap_sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    allowlist_id: str
    platform_execution_mode: str
    descriptor_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _id(self.implementation_version)
        _sha(self.bootstrap_sha256)
        for value in (self.size, self.device, self.inode, self.mtime_ns, self.ctime_ns):
            _int(value, minimum=0, maximum=2**63 - 1, code="producer_bootstrap_identity_invalid")
        _id(self.allowlist_id)
        if self.platform_execution_mode not in {"darwin-immutable-snapshot", "linux-fd-bound", "fixture-only"}:
            _fail("producer_bootstrap_platform_mode_invalid")
        if self.descriptor_sha256 is not None and self.descriptor_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.descriptor_sha256 is None:
            object.__setattr__(self, "descriptor_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "implementation_version": self.implementation_version, "bootstrap_sha256": self.bootstrap_sha256,
            "size": self.size, "device": self.device, "inode": self.inode,
            "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns, "allowlist_id": self.allowlist_id,
            "platform_execution_mode": self.platform_execution_mode,
        }
        if include_digest:
            value["descriptor_sha256"] = self.descriptor_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "descriptor_sha256")


_LAUNCH_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256", "target_executable_identity",
    "gate_protocol", "gate_nonce", "launch_sha256",
})


@dataclass(frozen=True, slots=True)
class TrustedBootstrapLaunch:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    attestation_sha256: str
    bootstrap_descriptor_sha256: str
    target_executable_identity: str
    gate_protocol: str
    gate_nonce: str
    launch_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        for value in (self.launch_id, self.journal_id, self.run_id, self.parent_task_id, self.task_id, self.gate_nonce):
            _id(value)
        for value in (self.intent_sha256, self.attestation_sha256, self.bootstrap_descriptor_sha256, self.target_executable_identity):
            _sha(value)
        if self.gate_protocol != "fd-read-one-byte-v1":
            _fail("producer_bootstrap_gate_protocol_invalid")
        if self.launch_sha256 is not None and self.launch_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.launch_sha256 is None:
            object.__setattr__(self, "launch_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "launch_id": self.launch_id, "journal_id": self.journal_id, "run_id": self.run_id,
            "parent_task_id": self.parent_task_id, "task_id": self.task_id,
            "intent_sha256": self.intent_sha256, "attestation_sha256": self.attestation_sha256,
            "bootstrap_descriptor_sha256": self.bootstrap_descriptor_sha256,
            "target_executable_identity": self.target_executable_identity,
            "gate_protocol": self.gate_protocol, "gate_nonce": self.gate_nonce,
        }
        if include_digest:
            value["launch_sha256"] = self.launch_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "launch_sha256")


_FRAME_FIELDS = frozenset({
    "schema_version", "protocol", "sequence", "kind", "launch_sha256", "intent_sha256",
    "target_executable_identity", "observed_pid", "observed_pgid", "frame_sha256",
})


@dataclass(frozen=True, slots=True)
class BootstrapHandshakeFrame:
    sequence: int
    kind: str
    launch_sha256: str
    intent_sha256: str
    target_executable_identity: str | None = None
    observed_pid: int | None = None
    observed_pgid: int | None = None
    frame_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _int(self.sequence, minimum=1, maximum=MAX_BOOTSTRAP_SEQUENCE, code="producer_bootstrap_sequence_invalid")
        if self.kind not in _KINDS:
            _fail("producer_bootstrap_frame_kind_invalid")
        _sha(self.launch_sha256)
        _sha(self.intent_sha256)
        if self.target_executable_identity is not None:
            _sha(self.target_executable_identity)
        for value in (self.observed_pid, self.observed_pgid):
            if value is not None:
                _int(value, minimum=2, maximum=2**63 - 1, code="producer_bootstrap_process_identity_invalid")
        if self.kind == "target_started" and (
            self.target_executable_identity is None or self.observed_pid is None or self.observed_pgid is None
        ):
            _fail("producer_bootstrap_target_frame_invalid")
        if self.kind != "target_started" and any(
            value is not None for value in (self.target_executable_identity, self.observed_pid, self.observed_pgid)
        ):
            _fail("producer_bootstrap_target_frame_invalid")
        if self.frame_sha256 is not None and self.frame_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.frame_sha256 is None:
            object.__setattr__(self, "frame_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "sequence": self.sequence, "kind": self.kind, "launch_sha256": self.launch_sha256,
            "intent_sha256": self.intent_sha256, "target_executable_identity": self.target_executable_identity,
            "observed_pid": self.observed_pid, "observed_pgid": self.observed_pgid,
        }
        if include_digest:
            value["frame_sha256"] = self.frame_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "frame_sha256")


def parse_bootstrap_handshake_frame(value: object) -> BootstrapHandshakeFrame:
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _FRAME_FIELDS, "producer_bootstrap_frame_schema_invalid")
    try:
        return BootstrapHandshakeFrame(**raw)
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_frame_schema_invalid") from exc


@dataclass(frozen=True, slots=True)
class TrustedBootstrapEvidence:
    launch_sha256: str
    registration_sha256: str
    bootstrap_ready_observed: bool
    release_observed: bool
    target_started_observed: bool
    target_start_count: int
    target_group_identity: str | None
    pre_gate_target_work_observed: bool
    status: str
    failure_code: str | None = None
    evidence_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _sha(self.launch_sha256)
        _sha(self.registration_sha256)
        if not all(isinstance(value, bool) for value in (
            self.bootstrap_ready_observed, self.release_observed,
            self.target_started_observed, self.pre_gate_target_work_observed,
        )):
            _fail("producer_bootstrap_evidence_boolean_invalid")
        _int(self.target_start_count, minimum=0, maximum=1, code="producer_bootstrap_target_count_invalid")
        if self.target_group_identity is not None:
            _sha(self.target_group_identity)
        if self.status not in _STATUSES:
            _fail("producer_bootstrap_status_invalid")
        if self.status == "failed" and not self.failure_code:
            _fail("producer_bootstrap_failure_code_missing")
        if self.status != "failed" and self.failure_code is not None:
            _fail("producer_bootstrap_failure_code_unexpected")
        if self.status == "passed" and (
            not self.bootstrap_ready_observed or not self.release_observed
            or not self.target_started_observed or self.target_start_count != 1
            or self.pre_gate_target_work_observed or self.target_group_identity is None
        ):
            _fail("producer_bootstrap_evidence_incomplete")
        if self.evidence_sha256 is not None and self.evidence_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.evidence_sha256 is None:
            object.__setattr__(self, "evidence_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "launch_sha256": self.launch_sha256, "registration_sha256": self.registration_sha256,
            "bootstrap_ready_observed": self.bootstrap_ready_observed, "release_observed": self.release_observed,
            "target_started_observed": self.target_started_observed, "target_start_count": self.target_start_count,
            "target_group_identity": self.target_group_identity,
            "pre_gate_target_work_observed": self.pre_gate_target_work_observed,
            "status": self.status, "failure_code": self.failure_code,
        }
        if include_digest:
            value["evidence_sha256"] = self.evidence_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "evidence_sha256")


class TrustedBootstrapSession:
    """Small deterministic state machine for the trusted bootstrap handshake."""

    def __init__(self, launch: TrustedBootstrapLaunch, registration_sha256: str) -> None:
        _sha(registration_sha256)
        self.launch = launch
        self.registration_sha256 = registration_sha256
        self.state = "created"
        # Keep observations separate from the current state.  A failed session is also
        # terminal, but reaching ``terminal`` does not imply that the ready frame was
        # ever observed.
        self.bootstrap_ready_observed = False
        self.release_count = 0
        self.target_start_count = 0
        self.pre_gate_target_work_observed = False
        self.target_group_identity: str | None = None
        self.failure_code: str | None = None

    def _check_frame(self, frame: BootstrapHandshakeFrame) -> None:
        if frame.launch_sha256 != self.launch.launch_sha256 or frame.intent_sha256 != self.launch.intent_sha256:
            _fail("producer_bootstrap_frame_binding_mismatch")

    def accept_frame(self, frame: BootstrapHandshakeFrame | object) -> None:
        # A successful terminal frame closes the handshake just like a failure does.
        # Do not let a late frame turn a successful start into a second start or let a
        # malformed late frame mutate the evidence a second time.
        if self.state == "terminal" or self.failure_code is not None:
            _fail("producer_bootstrap_terminal")
        if not isinstance(frame, BootstrapHandshakeFrame):
            try:
                frame = parse_bootstrap_handshake_frame(frame)
            except ProducerBootstrapError as exc:
                # A malformed frame is a definitive protocol failure once a live
                # session has accepted responsibility for the handshake.
                self.fail(exc.code)
        try:
            self._check_frame(frame)
        except ProducerBootstrapError as exc:
            self.fail(exc.code)
        if frame.kind == "bootstrap_ready":
            if self.state != "created" or frame.sequence != 1:
                self.fail("producer_bootstrap_ready_order_invalid")
            self.bootstrap_ready_observed = True
            self.state = "ready"
            return
        if frame.kind == "target_started":
            if self.state == "target_started":
                self.fail("producer_bootstrap_duplicate_target_start")
            if self.state != "released" or frame.sequence != 2:
                self.fail("producer_bootstrap_target_started_before_release")
            if frame.target_executable_identity != self.launch.target_executable_identity:
                self.fail("producer_bootstrap_target_identity_mismatch")
            self.target_start_count += 1
            if self.target_start_count != 1:
                self.fail("producer_bootstrap_duplicate_target_start")
            self.target_group_identity = hashlib.sha256(
                _canonical({"pid": frame.observed_pid, "pgid": frame.observed_pgid})
            ).hexdigest()
            self.state = "target_started"
            return
        if frame.kind == "target_start_failed":
            if self.state != "released" or frame.sequence != 2:
                self.fail("producer_bootstrap_target_start_order_invalid")
            self.fail("producer_bootstrap_target_start_failed")
        if frame.kind == "terminal":
            # ``terminal`` is the optional final frame after the target-start frame.
            # A released bootstrap that never reported target start must use the
            # explicit target_start_failed frame; accepting terminal here would make
            # an incomplete launch look orderly.
            if self.state != "target_started" or frame.sequence != 3:
                self.fail("producer_bootstrap_terminal_order_invalid")
            self.state = "terminal"
            return
        self.fail("producer_bootstrap_frame_kind_invalid")

    def release(self, token: str) -> None:
        if self.state == "terminal":
            self.fail("producer_bootstrap_terminal")
        if self.state == "released":
            self.fail("producer_bootstrap_duplicate_release")
        if self.state != "ready":
            self.fail("producer_bootstrap_release_order_invalid")
        if token != self.launch.gate_nonce:
            self.fail("producer_bootstrap_release_token_invalid")
        self.release_count += 1
        if self.release_count != 1:
            self.fail("producer_bootstrap_duplicate_release")
        self.state = "released"

    def record_eof(self) -> None:
        """Close the handshake after start, or reject EOF before a target start."""
        if self.state in {"created", "ready", "released"}:
            self.fail("producer_bootstrap_early_eof")
        if self.state == "target_started":
            self.state = "terminal"
            return
        self.fail("producer_bootstrap_terminal")

    def record_pre_gate_target_work(self) -> None:
        if self.state in {"created", "ready"}:
            self.pre_gate_target_work_observed = True
            self.fail("producer_bootstrap_pre_gate_work")
        _fail("producer_bootstrap_terminal")

    def fail(self, code: str) -> None:
        # Once a terminal frame or terminal failure has been recorded, keep the
        # evidence immutable.  A late API call is rejected without downgrading a
        # previously successful handshake to ``failed``.
        if self.state == "terminal" or self.failure_code is not None:
            _fail("producer_bootstrap_terminal")
        self.failure_code = code
        self.state = "terminal"
        raise ProducerBootstrapError(code)

    def evidence(self) -> TrustedBootstrapEvidence:
        passed = (
            self.state == "terminal" and self.release_count == 1
            and self.target_start_count == 1 and not self.pre_gate_target_work_observed
            and self.target_group_identity is not None and self.failure_code is None
        )
        return TrustedBootstrapEvidence(
            launch_sha256=self.launch.launch_sha256 or self.launch.digest(),
            registration_sha256=self.registration_sha256,
            bootstrap_ready_observed=self.bootstrap_ready_observed,
            release_observed=self.release_count == 1,
            target_started_observed=self.target_start_count == 1,
            target_start_count=self.target_start_count,
            target_group_identity=self.target_group_identity,
            pre_gate_target_work_observed=self.pre_gate_target_work_observed,
            status="passed" if passed else ("failed" if self.failure_code else "unknown"),
            failure_code=self.failure_code,
        )


__all__ = [
    "MAX_BOOTSTRAP_PAYLOAD_BYTES",
    "TRUSTED_BOOTSTRAP_PROTOCOL",
    "TRUSTED_BOOTSTRAP_SCHEMA_VERSION",
    "BootstrapHandshakeFrame",
    "ProducerBootstrapError",
    "TrustedBootstrapDescriptor",
    "TrustedBootstrapEvidence",
    "TrustedBootstrapLaunch",
    "TrustedBootstrapSession",
    "parse_bootstrap_handshake_frame",
]
