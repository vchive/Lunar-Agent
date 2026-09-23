"""Provider-free contract and zero-write admission for external producers.

Feature 154 intentionally stops before process creation.  The launch intent contains only
canonical, bounded declarations.  A later launcher may use it to perform an exact no-shell
handshake, but this module never starts a process, writes a receipt, or publishes output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as _files

PRODUCER_LAUNCH_PROTOCOL = "lunar-producer-launch-intent-v1"
PRODUCER_LAUNCH_SCHEMA_VERSION = "1"
MAX_PRODUCER_LAUNCH_BYTES = 128 * 1024
MAX_ARGV = 64
MAX_ARG_BYTES = 4096
MAX_ENVIRONMENT_BYTES = 4096
MAX_REQUEST_TIMEOUT_SECONDS = 86_400
MAX_REQUESTS = 10_000_000_000
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_WALL_TIMEOUT_SECONDS = 86_400

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,4095}$")
_CREDENTIAL = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|password|secret|access[_-]?token|credential)"
    r"\s*[:= ]\s*\S+"
)
_SHELL = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh"})
_INTENT_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
    "generator_fingerprint", "dependency_sha256", "environment_sha256", "producer_id", "producer_fingerprint",
    "executable_root_label", "executable_relative", "executable_sha256", "executable_size",
    "executable_device", "executable_inode", "executable_mtime_ns", "executable_ctime_ns", "argv",
    "argv_sha256", "working_directory", "output_directory", "envelope_path",
    "request_timeout_seconds", "max_requests", "output_max_bytes", "wall_timeout_seconds", "intent_sha256",
})
_ATTESTATION_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "intent_sha256", "executable_sha256", "executable_size", "executable_device", "executable_inode",
    "executable_mtime_ns", "executable_ctime_ns", "nonce", "attestation_sha256",
})
_PREFLIGHT_FIELDS = frozenset({
    "schema_version", "protocol", "status", "launch_id", "journal_id", "run_id", "parent_task_id",
    "task_id", "intent_sha256", "budget_sha256", "executable_sha256", "executable_identity",
    "derived_output_directory", "registration_attestation_required",
})


class ProducerLaunchError(ValueError):
    """Fixed-code failure without producer-controlled paths or prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerLaunchError(code)


def _canonical(value: object, maximum: int = MAX_PRODUCER_LAUNCH_BYTES) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerLaunchError("producer_launch_canonical_invalid") from exc
    if len(data) > maximum:
        _fail("producer_launch_too_large")
    return data


def _strict_json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProducerLaunchError("producer_launch_json_invalid") from exc
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_PRODUCER_LAUNCH_BYTES:
        _fail("producer_launch_json_invalid")
    seen: set[str] = set()

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in seen:
                _fail("producer_launch_duplicate_key")
            seen.add(key)
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: _fail("producer_launch_json_invalid"))
    except ProducerLaunchError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProducerLaunchError("producer_launch_json_invalid") from exc


def _object(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("producer_launch_schema_invalid")
    return value


def _sha(value: object, code: str = "producer_launch_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "producer_launch_identifier_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None or _CREDENTIAL.search(value):
        _fail(code)
    return value


def _path(value: object, code: str = "producer_launch_path_invalid") -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value or _CREDENTIAL.search(value):
        _fail(code)
    raw = Path(value)
    if raw.is_absolute() or raw.as_posix() != value or any(part in {"", ".", ".."} for part in raw.parts) or _PATH.fullmatch(value) is None:
        _fail(code)
    return value


def _label(value: object, code: str = "producer_launch_label_invalid") -> str:
    if not isinstance(value, str) or _LABEL.fullmatch(value) is None:
        _fail(code)
    return value


def _positive(value: object, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        _fail(code)
    return value


def _argv(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ARGV or any(not isinstance(item, str) for item in value):
        _fail("producer_launch_argv_invalid")
    result = tuple(value)
    for index, item in enumerate(result):
        if not item or "\x00" in item or len(item.encode("utf-8")) > MAX_ARG_BYTES or _CREDENTIAL.search(item):
            _fail("producer_launch_argv_invalid")
        if any(char in item for char in ";&|`\n\r") or (index and item in {"-c", "--command", "/c", "-Command"}):
            _fail("producer_launch_shell_unsupported")
    if Path(result[0]).name.casefold() in _SHELL:
        _fail("producer_launch_shell_unsupported")
    return result


def _stat_file(path: Path) -> tuple[str, int, int, int, int, int]:
    try:
        info = os.lstat(path)
        data = _files.read_regular_file(_files.absolute_path(path), MAX_OUTPUT_BYTES)
    except Exception as exc:
        raise ProducerLaunchError("producer_launch_executable_invalid") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("producer_launch_executable_invalid")
    return hashlib.sha256(data).hexdigest(), info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns


def _confined_file(root: Path, relative: str) -> Path:
    """Resolve a relative executable without following a symlinked ancestor."""
    current = root
    parts = Path(relative).parts
    for part in parts[:-1]:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise ProducerLaunchError("producer_launch_executable_invalid") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            _fail("producer_launch_executable_invalid")
    return current / parts[-1]


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class ProducerLaunchIntent:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    runner_fingerprint: str
    generator_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    producer_id: str
    producer_fingerprint: str
    executable_root_label: str
    executable_relative: str
    executable_sha256: str
    executable_size: int
    executable_device: int
    executable_inode: int
    executable_mtime_ns: int
    executable_ctime_ns: int
    argv: tuple[str, ...]
    argv_sha256: str
    working_directory: str
    output_directory: str
    envelope_path: str
    request_timeout_seconds: int
    max_requests: int
    output_max_bytes: int
    wall_timeout_seconds: int
    intent_sha256: str | None = None
    schema_version: str = PRODUCER_LAUNCH_SCHEMA_VERSION
    protocol: str = PRODUCER_LAUNCH_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCER_LAUNCH_SCHEMA_VERSION or self.protocol != PRODUCER_LAUNCH_PROTOCOL:
            _fail("producer_launch_schema_invalid")
        for value, code in ((self.launch_id, "producer_launch_launch_invalid"), (self.journal_id, "producer_launch_journal_invalid"), (self.run_id, "producer_launch_run_invalid"), (self.parent_task_id, "producer_launch_parent_invalid"), (self.task_id, "producer_launch_task_invalid"), (self.producer_id, "producer_launch_producer_invalid")):
            _identifier(value, code)
        for value, code in ((self.contract_sha256, "producer_launch_contract_invalid"), (self.evaluator_fingerprint, "producer_launch_evaluator_invalid"), (self.runner_fingerprint, "producer_launch_runner_invalid"), (self.generator_fingerprint, "producer_launch_generator_invalid"), (self.dependency_sha256, "producer_launch_dependency_invalid"), (self.environment_sha256, "producer_launch_environment_digest_invalid"), (self.producer_fingerprint, "producer_launch_producer_digest_invalid")):
            _sha(value, code)
        _label(self.evaluator_kind, "producer_launch_evaluator_kind_invalid")
        _label(self.executable_root_label)
        _path(self.executable_relative)
        _sha(self.executable_sha256, "producer_launch_executable_digest_invalid")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (self.executable_size, self.executable_device, self.executable_inode, self.executable_mtime_ns, self.executable_ctime_ns)):
            _fail("producer_launch_executable_stat_invalid")
        argv = _argv(list(self.argv))
        if argv[0] != self.executable_relative:
            _fail("producer_launch_argv_executable_mismatch")
        if hashlib.sha256(_canonical(list(argv))).hexdigest() != self.argv_sha256:
            _fail("producer_launch_argv_digest_invalid")
        for value in (self.working_directory, self.output_directory, self.envelope_path):
            _path(value)
        if self.envelope_path != self.output_directory + "/producer-result.json":
            _fail("producer_launch_output_invalid")
        _positive(self.request_timeout_seconds, MAX_REQUEST_TIMEOUT_SECONDS, "producer_launch_request_timeout_invalid")
        _positive(self.max_requests, MAX_REQUESTS, "producer_launch_request_budget_invalid")
        _positive(self.output_max_bytes, MAX_OUTPUT_BYTES, "producer_launch_output_budget_invalid")
        _positive(self.wall_timeout_seconds, MAX_WALL_TIMEOUT_SECONDS, "producer_launch_wall_timeout_invalid")
        if self.wall_timeout_seconds < self.request_timeout_seconds:
            _fail("producer_launch_wall_timeout_invalid")
        if self.intent_sha256 is not None and _digest_without(self.to_dict(), "intent_sha256") != self.intent_sha256:
            _fail("producer_launch_intent_digest_mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "protocol": self.protocol, "launch_id": self.launch_id,
            "journal_id": self.journal_id, "run_id": self.run_id, "parent_task_id": self.parent_task_id,
            "task_id": self.task_id, "contract_sha256": self.contract_sha256, "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint, "runner_fingerprint": self.runner_fingerprint,
            "generator_fingerprint": self.generator_fingerprint, "dependency_sha256": self.dependency_sha256, "environment_sha256": self.environment_sha256,
            "producer_id": self.producer_id, "producer_fingerprint": self.producer_fingerprint,
            "executable_root_label": self.executable_root_label, "executable_relative": self.executable_relative,
            "executable_sha256": self.executable_sha256, "executable_size": self.executable_size,
            "executable_device": self.executable_device, "executable_inode": self.executable_inode,
            "executable_mtime_ns": self.executable_mtime_ns, "executable_ctime_ns": self.executable_ctime_ns,
            "argv": list(self.argv), "argv_sha256": self.argv_sha256, "working_directory": self.working_directory,
            "output_directory": self.output_directory, "envelope_path": self.envelope_path,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_requests": self.max_requests, "output_max_bytes": self.output_max_bytes,
            "wall_timeout_seconds": self.wall_timeout_seconds, "intent_sha256": self.intent_sha256,
        }

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "intent_sha256")


def parse_producer_launch_intent(value: object) -> ProducerLaunchIntent:
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _INTENT_FIELDS)
    if not isinstance(raw.get("argv"), list):
        _fail("producer_launch_argv_invalid")
    try:
        return ProducerLaunchIntent(**{**raw, "argv": tuple(raw["argv"])})
    except ProducerLaunchError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerLaunchError("producer_launch_schema_invalid") from exc


def build_producer_launch_intent(
    *, producer_root: str | Path, launch_id: str, journal_id: str, run_id: str, parent_task_id: str,
    task_id: str, contract_sha256: str, evaluator_kind: str, evaluator_fingerprint: str,
    runner_fingerprint: str, generator_fingerprint: str, dependency_sha256: str, environment_sha256: str,
    producer_id: str, producer_fingerprint: str, executable_relative: str, argv: Sequence[str],
    working_directory: str, output_directory: str,
    request_timeout_seconds: int, max_requests: int, output_max_bytes: int, wall_timeout_seconds: int,
) -> ProducerLaunchIntent:
    """Pin an executable below ``producer_root`` without launching or writing anything."""
    root = Path(producer_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        _fail("producer_launch_root_invalid")
    executable = _confined_file(root, _path(executable_relative))
    digest, size, device, inode, mtime_ns, ctime_ns = _stat_file(executable)
    intent = ProducerLaunchIntent(
        launch_id=launch_id, journal_id=journal_id, run_id=run_id, parent_task_id=parent_task_id, task_id=task_id,
        contract_sha256=contract_sha256,
        evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint, runner_fingerprint=runner_fingerprint,
        generator_fingerprint=generator_fingerprint, dependency_sha256=dependency_sha256, environment_sha256=environment_sha256, producer_id=producer_id,
        producer_fingerprint=producer_fingerprint, executable_root_label="producer-root", executable_relative=executable_relative,
        executable_sha256=digest, executable_size=size, executable_device=device, executable_inode=inode,
        executable_mtime_ns=mtime_ns, executable_ctime_ns=ctime_ns, argv=tuple(argv),
        argv_sha256=hashlib.sha256(_canonical(list(argv))).hexdigest(), working_directory=working_directory,
        output_directory=output_directory, envelope_path=output_directory + "/producer-result.json",
        request_timeout_seconds=request_timeout_seconds, max_requests=max_requests,
        output_max_bytes=output_max_bytes, wall_timeout_seconds=wall_timeout_seconds,
    )
    return ProducerLaunchIntent(**{**intent.to_dict(), "argv": tuple(intent.argv), "intent_sha256": intent.digest()})


@dataclass(frozen=True, slots=True)
class ProducerLaunchAttestation:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    executable_sha256: str
    executable_size: int
    executable_device: int
    executable_inode: int
    executable_mtime_ns: int
    executable_ctime_ns: int
    nonce: str
    attestation_sha256: str | None = None
    schema_version: str = PRODUCER_LAUNCH_SCHEMA_VERSION
    protocol: str = PRODUCER_LAUNCH_PROTOCOL

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "launch_id": self.launch_id, "journal_id": self.journal_id, "run_id": self.run_id, "parent_task_id": self.parent_task_id, "task_id": self.task_id, "intent_sha256": self.intent_sha256, "executable_sha256": self.executable_sha256, "executable_size": self.executable_size, "executable_device": self.executable_device, "executable_inode": self.executable_inode, "executable_mtime_ns": self.executable_mtime_ns, "executable_ctime_ns": self.executable_ctime_ns, "nonce": self.nonce, "attestation_sha256": self.attestation_sha256}

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "attestation_sha256")


def parse_producer_launch_attestation(value: object) -> ProducerLaunchAttestation:
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _ATTESTATION_FIELDS)
    try:
        item = ProducerLaunchAttestation(**raw)
    except (TypeError, ValueError) as exc:
        raise ProducerLaunchError("producer_launch_attestation_invalid") from exc
    for field in ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "nonce"):
        _identifier(getattr(item, field), "producer_launch_attestation_invalid")
    _sha(item.intent_sha256, "producer_launch_attestation_invalid")
    _sha(item.executable_sha256, "producer_launch_attestation_invalid")
    if item.attestation_sha256 != item.digest():
        _fail("producer_launch_attestation_digest_mismatch")
    return item


def build_producer_launch_attestation(intent: ProducerLaunchIntent, nonce: str) -> ProducerLaunchAttestation:
    """Create the one-time attestation payload for an already pinned intent.

    The nonce is supplied by the caller and is intentionally not persisted here.  A future
    process registrar must consume it exactly once and retain its own replay guard.
    """
    if not isinstance(intent, ProducerLaunchIntent):
        _fail("producer_launch_intent_invalid")
    _identifier(nonce, "producer_launch_attestation_nonce_invalid")
    item = ProducerLaunchAttestation(
        launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
        parent_task_id=intent.parent_task_id, task_id=intent.task_id,
        intent_sha256=intent.intent_sha256 or intent.digest(), executable_sha256=intent.executable_sha256,
        executable_size=intent.executable_size, executable_device=intent.executable_device,
        executable_inode=intent.executable_inode, executable_mtime_ns=intent.executable_mtime_ns,
        executable_ctime_ns=intent.executable_ctime_ns, nonce=nonce,
    )
    return ProducerLaunchAttestation(**{**item.to_dict(), "attestation_sha256": item.digest()})


def verify_producer_launch_attestation(
    intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation | object,
) -> None:
    """Check the exact parent/child/task, intent and executable identity tuple."""
    if not isinstance(intent, ProducerLaunchIntent):
        _fail("producer_launch_intent_invalid")
    if not isinstance(attestation, ProducerLaunchAttestation):
        attestation = parse_producer_launch_attestation(attestation)
    expected = {
        "launch_id": intent.launch_id, "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "intent_sha256": intent.intent_sha256 or intent.digest(), "executable_sha256": intent.executable_sha256,
        "executable_size": intent.executable_size, "executable_device": intent.executable_device,
        "executable_inode": intent.executable_inode, "executable_mtime_ns": intent.executable_mtime_ns,
        "executable_ctime_ns": intent.executable_ctime_ns,
    }
    if any(getattr(attestation, key) != value for key, value in expected.items()):
        _fail("producer_launch_attestation_mismatch")
    if attestation.attestation_sha256 != attestation.digest():
        _fail("producer_launch_attestation_digest_mismatch")


@dataclass(frozen=True, slots=True)
class ProducerLaunchPreflight:
    status: str
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    budget_sha256: str
    executable_sha256: str
    executable_identity: str
    derived_output_directory: str
    registration_attestation_required: bool = True
    schema_version: str = PRODUCER_LAUNCH_SCHEMA_VERSION
    protocol: str = PRODUCER_LAUNCH_PROTOCOL

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "status": self.status, "launch_id": self.launch_id, "journal_id": self.journal_id, "run_id": self.run_id, "parent_task_id": self.parent_task_id, "task_id": self.task_id, "intent_sha256": self.intent_sha256, "budget_sha256": self.budget_sha256, "executable_sha256": self.executable_sha256, "executable_identity": self.executable_identity, "derived_output_directory": self.derived_output_directory, "registration_attestation_required": self.registration_attestation_required}


def parse_producer_launch_preflight(value: object) -> ProducerLaunchPreflight:
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _PREFLIGHT_FIELDS)
    try:
        item = ProducerLaunchPreflight(**raw)
    except (TypeError, ValueError) as exc:
        raise ProducerLaunchError("producer_launch_admission_invalid") from exc
    if item.status not in {"preflight_passed", "rejected"} or not item.registration_attestation_required:
        _fail("producer_launch_preflight_invalid")
    for field in ("intent_sha256", "budget_sha256", "executable_sha256"):
        _sha(getattr(item, field), "producer_launch_preflight_invalid")
    _path(item.derived_output_directory)
    return item


def _root(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ProducerLaunchError("producer_launch_workspace_invalid") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _fail("producer_launch_workspace_invalid")
    return path


def preflight_producer_launch(
    workspace: str | Path, intent: ProducerLaunchIntent | object, *, producer_root: str | Path,
    candidate_integrity_authority: object | None = None, expected_run_id: str | None = None,
    expected_parent_task_id: str | None = None, expected_task_id: str | None = None,
) -> ProducerLaunchPreflight:
    """Perform the provider-free, zero-write launch consistency observation."""
    if not isinstance(intent, ProducerLaunchIntent):
        intent = parse_producer_launch_intent(intent)
    root = _root(producer_root)
    # The authority and identity tuple are mandatory for a successful preflight.  Keep
    # the arguments optional at the Python boundary so malformed calls still return the
    # fixed provider-free error after path safety has been checked (useful for callers
    # probing an invalid/symlinked producer root).
    if candidate_integrity_authority is None:
        _fail("producer_launch_authority_invalid")
    if expected_run_id is None or expected_parent_task_id is None or expected_task_id is None:
        _fail("producer_launch_identity_invalid")
    if not isinstance(candidate_integrity_authority, Mapping):
        to_dict = getattr(candidate_integrity_authority, "to_dict", None)
        if not callable(to_dict):
            _fail("producer_launch_authority_invalid")
        candidate_integrity_authority = to_dict()
    authority = dict(candidate_integrity_authority)
    expected_authority = {
        "schema_version": "1",
        "contract_sha256": intent.contract_sha256, "evaluator_kind": intent.evaluator_kind,
        "evaluator_fingerprint": intent.evaluator_fingerprint, "dependency_sha256": intent.dependency_sha256,
        "environment_sha256": intent.environment_sha256, "runner_fingerprint": intent.runner_fingerprint,
        "generator_fingerprint": intent.generator_fingerprint,
    }
    if set(authority) != set(expected_authority):
        _fail("producer_launch_authority_mismatch")
    for field, expected in expected_authority.items():
        if authority.get(field) != expected:
            _fail("producer_launch_authority_mismatch")
    if (intent.run_id != expected_run_id or intent.parent_task_id != expected_parent_task_id
            or intent.task_id != expected_task_id):
        _fail("producer_launch_identity_mismatch")
    executable = _confined_file(root, intent.executable_relative)
    actual = _stat_file(executable)
    if actual != (intent.executable_sha256, intent.executable_size, intent.executable_device, intent.executable_inode, intent.executable_mtime_ns, intent.executable_ctime_ns):
        _fail("producer_launch_executable_changed")
    workspace_root = _root(workspace)
    # Only inspect derived components.  Missing directories are acceptable and are never created.
    def check_derived(relative: str) -> Path:
        derived_path = Path("evolution") / "producer-batches" / intent.journal_id / relative
        current = workspace_root
        for component in derived_path.parts:
            current = current / component
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                # A missing component means all descendants are necessarily missing; do not create
                # it as part of this read-only observation.
                break
            except OSError as exc:
                raise ProducerLaunchError("producer_launch_output_invalid") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _fail("producer_launch_output_invalid")
        return derived_path

    check_derived(intent.working_directory)
    derived = check_derived(intent.output_directory)
    budget = {"request_timeout_seconds": intent.request_timeout_seconds, "max_requests": intent.max_requests, "output_max_bytes": intent.output_max_bytes, "wall_timeout_seconds": intent.wall_timeout_seconds}
    return ProducerLaunchPreflight(
        status="preflight_passed", launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
        parent_task_id=intent.parent_task_id, task_id=intent.task_id, intent_sha256=intent.intent_sha256 or intent.digest(),
        budget_sha256=hashlib.sha256(_canonical(budget)).hexdigest(), executable_sha256=actual[0],
        executable_identity=hashlib.sha256(_canonical({"sha256": actual[0], "size": actual[1], "device": actual[2], "inode": actual[3], "mtime_ns": actual[4], "ctime_ns": actual[5]})).hexdigest(),
        derived_output_directory=derived.as_posix(),
    )


# Compatibility aliases for callers that used the provisional admission spelling before the
# read-only observation semantics were finalized.
ProducerLaunchAdmission = ProducerLaunchPreflight
parse_producer_launch_admission = parse_producer_launch_preflight


__all__ = [
    "PRODUCER_LAUNCH_PROTOCOL",
    "PRODUCER_LAUNCH_SCHEMA_VERSION",
    "ProducerLaunchAdmission",
    "ProducerLaunchAttestation",
    "ProducerLaunchError",
    "ProducerLaunchIntent",
    "ProducerLaunchPreflight",
    "build_producer_launch_attestation",
    "build_producer_launch_intent",
    "parse_producer_launch_admission",
    "parse_producer_launch_attestation",
    "parse_producer_launch_intent",
    "parse_producer_launch_preflight",
    "preflight_producer_launch",
    "verify_producer_launch_attestation",
]
