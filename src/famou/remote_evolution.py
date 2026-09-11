"""Bounded, transport-free contracts for an optional remote evolution backend.

The module deliberately contains no network or subprocess implementation.  A backend owns only
the remote experiment lifecycle and material references; it cannot create a Lunar candidate or an
``EvaluationReport``.  Synchronized material therefore remains untrusted until the separate local
seed-admission boundary evaluates it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

REMOTE_EVOLUTION_SCHEMA_VERSION = "1"
MAX_REMOTE_MATERIALS = 32
MAX_REMOTE_MATERIAL_BYTES = 16 * 1024 * 1024
MAX_REMOTE_TOTAL_MATERIAL_BYTES = 64 * 1024 * 1024
MAX_REMOTE_ITERATIONS = 10_000
MAX_REMOTE_ATTEMPTS = 1_000_000
MAX_REMOTE_TIMESTAMP_MS = 253_402_300_799_999
MAX_REMOTE_PAYLOAD_BYTES = 64 * 1024

RemoteLifecycleStatus = Literal[
    "submitted", "running", "completed", "cancelled", "failed", "unknown"
]

REMOTE_LIFECYCLE_STATUSES = frozenset(
    {"submitted", "running", "completed", "cancelled", "failed", "unknown"}
)
REMOTE_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_KIND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+)"
)

_ALLOWED_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "submitted": frozenset({"submitted", "running", "unknown", "cancelled"}),
    "running": frozenset({"running", "completed", "failed", "unknown", "cancelled"}),
    "unknown": frozenset({"unknown", "running", "completed", "failed"}),
    "completed": frozenset({"completed"}),
    "cancelled": frozenset({"cancelled"}),
    "failed": frozenset({"failed"}),
}


class RemoteEvolutionError(ValueError):
    """Malformed remote lifecycle evidence or an illegal local operation."""


def _fail(message: str) -> None:
    raise RemoteEvolutionError(message)


def _strict_object(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    missing = required - set(value)
    extra = set(value) - required
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unsupported " + ", ".join(sorted(extra)))
        _fail(f"{label} has invalid fields ({'; '.join(details)})")
    return value


def _schema(value: object, label: str) -> None:
    if value != REMOTE_EVOLUTION_SCHEMA_VERSION:
        _fail(f"{label} schema_version must be {REMOTE_EVOLUTION_SCHEMA_VERSION!r}")


def _identifier(value: object, label: str, *, kind: bool = False) -> str:
    pattern = _SAFE_KIND if kind else _SAFE_ID
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail(f"{label} must be a safe bounded identifier")
    if _SECRET.search(value):
        _fail(f"{label} contains credential-like content")
    return value


def _optional_experiment_id(value: object, status: str, label: str = "experiment_id") -> str | None:
    if value is None:
        if status != "unknown":
            _fail(f"{label} may be null only for unknown state")
        return None
    return _identifier(value, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _timestamp(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _integer(value, label, 0, MAX_REMOTE_TIMESTAMP_MS)


def _relative_path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 1_024
        or "\\" in value
        or "\x00" in value
        or _SECRET.search(value)
    ):
        _fail(f"{label} must be a credential-safe bounded relative path")
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or value != path.as_posix()
    ):
        _fail(f"{label} must be a confined POSIX relative path")
    return path.as_posix()


def _bounded_payload(value: Mapping[str, object], label: str) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RemoteEvolutionError(f"{label} is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_REMOTE_PAYLOAD_BYTES:
        _fail(f"{label} exceeds the bounded payload size")
    if _SECRET.search(encoded):
        _fail(f"{label} contains credential-like content")


@dataclass(frozen=True, slots=True)
class RemoteMaterialReference:
    """One digest-bound, score-free material reference reported by a remote backend."""

    kind: str
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identifier(self.kind, "material kind", kind=True))
        object.__setattr__(self, "path", _relative_path(self.path, "material path"))
        _integer(self.size, "material size", 0, MAX_REMOTE_MATERIAL_BYTES)
        _digest(self.sha256, "material sha256")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "path": self.path, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: object) -> RemoteMaterialReference:
        item = _strict_object(value, {"kind", "path", "size", "sha256"}, "remote material")
        return cls(
            kind=item["kind"],  # type: ignore[arg-type]
            path=item["path"],  # type: ignore[arg-type]
            size=item["size"],  # type: ignore[arg-type]
            sha256=item["sha256"],  # type: ignore[arg-type]
        )


def _materials(
    value: Sequence[RemoteMaterialReference], *, required: bool, label: str = "materials"
) -> tuple[RemoteMaterialReference, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(f"{label} must be a bounded material sequence")
    result = tuple(value)
    minimum = 1 if required else 0
    if not minimum <= len(result) <= MAX_REMOTE_MATERIALS:
        qualifier = "non-empty " if required else ""
        _fail(f"{label} must be a bounded {qualifier}material sequence")
    if any(not isinstance(item, RemoteMaterialReference) for item in result):
        _fail(f"{label} must contain RemoteMaterialReference records")
    paths = [item.path for item in result]
    if len(paths) != len(set(paths)):
        _fail(f"{label} paths must be unique")
    if sum(item.size for item in result) > MAX_REMOTE_TOTAL_MATERIAL_BYTES:
        _fail(f"{label} exceed the bounded aggregate size")
    return result


def _material_list(value: object, label: str) -> tuple[RemoteMaterialReference, ...]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return tuple(RemoteMaterialReference.from_dict(item) for item in value)


@dataclass(frozen=True, slots=True)
class RemoteExperimentReference:
    """Stable lookup identity shared by all operations after submit."""

    experiment_id: str | None
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str

    def __post_init__(self) -> None:
        if self.experiment_id is not None:
            _identifier(self.experiment_id, "experiment_id")
        _identifier(self.idempotency_key, "idempotency_key")
        _identifier(self.producer_id, "producer_id")
        _digest(self.producer_fingerprint, "producer_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "idempotency_key": self.idempotency_key,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteExperimentReference:
        item = _strict_object(
            value,
            {
                "experiment_id",
                "idempotency_key",
                "producer_id",
                "producer_fingerprint",
            },
            "remote experiment reference",
        )
        return cls(
            experiment_id=item["experiment_id"],  # type: ignore[arg-type]
            idempotency_key=item["idempotency_key"],  # type: ignore[arg-type]
            producer_id=item["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=item["producer_fingerprint"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class RemoteSubmitRequest:
    """Credential-free request to create one remote experiment exactly once."""

    idempotency_key: str
    producer_id: str
    producer_fingerprint: str
    problem_id: str
    contract_sha256: str
    max_iterations: int
    materials: tuple[RemoteMaterialReference, ...]

    def __post_init__(self) -> None:
        _identifier(self.idempotency_key, "idempotency_key")
        _identifier(self.producer_id, "producer_id")
        _digest(self.producer_fingerprint, "producer_fingerprint")
        _identifier(self.problem_id, "problem_id")
        _digest(self.contract_sha256, "contract_sha256")
        _integer(self.max_iterations, "max_iterations", 1, MAX_REMOTE_ITERATIONS)
        object.__setattr__(self, "materials", _materials(self.materials, required=True))
        _bounded_payload(self.to_dict(), "remote submit request")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            "idempotency_key": self.idempotency_key,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "problem_id": self.problem_id,
            "contract_sha256": self.contract_sha256,
            "max_iterations": self.max_iterations,
            "materials": [item.to_dict() for item in self.materials],
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteSubmitRequest:
        item = _strict_object(
            value,
            {
                "schema_version",
                "idempotency_key",
                "producer_id",
                "producer_fingerprint",
                "problem_id",
                "contract_sha256",
                "max_iterations",
                "materials",
            },
            "remote submit request",
        )
        _schema(item["schema_version"], "remote submit request")
        return cls(
            idempotency_key=item["idempotency_key"],  # type: ignore[arg-type]
            producer_id=item["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=item["producer_fingerprint"],  # type: ignore[arg-type]
            problem_id=item["problem_id"],  # type: ignore[arg-type]
            contract_sha256=item["contract_sha256"],  # type: ignore[arg-type]
            max_iterations=item["max_iterations"],  # type: ignore[arg-type]
            materials=_material_list(item["materials"], "submit materials"),
        )


@dataclass(frozen=True, slots=True)
class RemoteStatusRequest:
    experiment_id: str | None
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str

    def __post_init__(self) -> None:
        RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    @property
    def reference(self) -> RemoteExperimentReference:
        return RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            **self.reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteStatusRequest:
        item = _request_object(value, "remote status request", set())
        return cls(
            item["experiment_id"],  # type: ignore[arg-type]
            item["idempotency_key"],  # type: ignore[arg-type]
            item["producer_id"],  # type: ignore[arg-type]
            item["producer_fingerprint"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_state(cls, state: RemoteExperimentState) -> RemoteStatusRequest:
        _state(state)
        return cls(
            state.experiment_id,
            state.idempotency_key,
            state.producer_id,
            state.producer_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class RemoteSyncRequest:
    experiment_id: str | None
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str

    def __post_init__(self) -> None:
        RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    @property
    def reference(self) -> RemoteExperimentReference:
        return RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            **self.reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteSyncRequest:
        item = _request_object(value, "remote sync request", set())
        return cls(
            item["experiment_id"],  # type: ignore[arg-type]
            item["idempotency_key"],  # type: ignore[arg-type]
            item["producer_id"],  # type: ignore[arg-type]
            item["producer_fingerprint"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_state(cls, state: RemoteExperimentState) -> RemoteSyncRequest:
        _state(state)
        return cls(
            state.experiment_id,
            state.idempotency_key,
            state.producer_id,
            state.producer_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class RemoteContinueRequest:
    experiment_id: str
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str
    operation_idempotency_key: str
    additional_iterations: int

    def __post_init__(self) -> None:
        if self.experiment_id is None:
            _fail("continue requires a reconciled experiment_id")
        RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )
        _identifier(self.operation_idempotency_key, "operation_idempotency_key")
        _integer(
            self.additional_iterations,
            "additional_iterations",
            1,
            MAX_REMOTE_ITERATIONS,
        )

    @property
    def reference(self) -> RemoteExperimentReference:
        return RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            **self.reference.to_dict(),
            "operation_idempotency_key": self.operation_idempotency_key,
            "additional_iterations": self.additional_iterations,
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteContinueRequest:
        item = _request_object(
            value,
            "remote continue request",
            {"operation_idempotency_key", "additional_iterations"},
        )
        return cls(
            experiment_id=item["experiment_id"],  # type: ignore[arg-type]
            idempotency_key=item["idempotency_key"],  # type: ignore[arg-type]
            producer_id=item["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=item["producer_fingerprint"],  # type: ignore[arg-type]
            operation_idempotency_key=item["operation_idempotency_key"],  # type: ignore[arg-type]
            additional_iterations=item["additional_iterations"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_state(
        cls,
        state: RemoteExperimentState,
        operation_idempotency_key: str,
        additional_iterations: int,
    ) -> RemoteContinueRequest:
        _require_actionable(state, "continue")
        if state.experiment_id is None:
            _fail("continue requires a reconciled experiment_id")
        return cls(
            state.experiment_id,
            state.idempotency_key,
            state.producer_id,
            state.producer_fingerprint,
            operation_idempotency_key,
            additional_iterations,
        )


@dataclass(frozen=True, slots=True)
class RemoteCancelRequest:
    experiment_id: str
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str
    operation_idempotency_key: str

    def __post_init__(self) -> None:
        if self.experiment_id is None:
            _fail("cancel requires a reconciled experiment_id")
        RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )
        _identifier(self.operation_idempotency_key, "operation_idempotency_key")

    @property
    def reference(self) -> RemoteExperimentReference:
        return RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            **self.reference.to_dict(),
            "operation_idempotency_key": self.operation_idempotency_key,
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteCancelRequest:
        item = _request_object(
            value, "remote cancel request", {"operation_idempotency_key"}
        )
        return cls(
            experiment_id=item["experiment_id"],  # type: ignore[arg-type]
            idempotency_key=item["idempotency_key"],  # type: ignore[arg-type]
            producer_id=item["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=item["producer_fingerprint"],  # type: ignore[arg-type]
            operation_idempotency_key=item["operation_idempotency_key"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_state(
        cls, state: RemoteExperimentState, operation_idempotency_key: str
    ) -> RemoteCancelRequest:
        _require_actionable(state, "cancel")
        if state.experiment_id is None:
            _fail("cancel requires a reconciled experiment_id")
        return cls(
            state.experiment_id,
            state.idempotency_key,
            state.producer_id,
            state.producer_fingerprint,
            operation_idempotency_key,
        )


def _request_object(value: object, label: str, extra: set[str]) -> dict[str, Any]:
    required = {
        "schema_version",
        "experiment_id",
        "idempotency_key",
        "producer_id",
        "producer_fingerprint",
        *extra,
    }
    item = _strict_object(value, required, label)
    _schema(item["schema_version"], label)
    return item


@dataclass(frozen=True, slots=True)
class RemoteExperimentState:
    """One bounded observation of a remote experiment; never local scoring evidence."""

    experiment_id: str | None
    idempotency_key: str
    producer_id: str
    producer_fingerprint: str
    status: RemoteLifecycleStatus
    submitted_at_ms: int | None
    updated_at_ms: int | None
    attempt_count: int
    materials: tuple[RemoteMaterialReference, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in REMOTE_LIFECYCLE_STATUSES:
            _fail("remote experiment status is unsupported")
        object.__setattr__(
            self,
            "experiment_id",
            _optional_experiment_id(self.experiment_id, self.status),
        )
        _identifier(self.idempotency_key, "idempotency_key")
        _identifier(self.producer_id, "producer_id")
        _digest(self.producer_fingerprint, "producer_fingerprint")
        submitted = _timestamp(self.submitted_at_ms, "submitted_at_ms")
        updated = _timestamp(self.updated_at_ms, "updated_at_ms")
        if submitted is not None and updated is not None and updated < submitted:
            _fail("updated_at_ms must not precede submitted_at_ms")
        _integer(self.attempt_count, "attempt_count", 1, MAX_REMOTE_ATTEMPTS)
        object.__setattr__(self, "materials", _materials(self.materials, required=False))
        _bounded_payload(self.to_dict(), "remote experiment state")

    @property
    def lifecycle_state(self) -> RemoteLifecycleStatus:
        """Compatibility spelling for callers that describe the field as lifecycle state."""

        return self.status

    @property
    def terminal(self) -> bool:
        return self.status in REMOTE_TERMINAL_STATUSES

    @property
    def reference(self) -> RemoteExperimentReference:
        return RemoteExperimentReference(
            self.experiment_id,
            self.idempotency_key,
            self.producer_id,
            self.producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_EVOLUTION_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "idempotency_key": self.idempotency_key,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "status": self.status,
            "submitted_at_ms": self.submitted_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "attempt_count": self.attempt_count,
            "materials": [item.to_dict() for item in self.materials],
        }

    @classmethod
    def from_dict(cls, value: object) -> RemoteExperimentState:
        item = _strict_object(
            value,
            {
                "schema_version",
                "experiment_id",
                "idempotency_key",
                "producer_id",
                "producer_fingerprint",
                "status",
                "submitted_at_ms",
                "updated_at_ms",
                "attempt_count",
                "materials",
            },
            "remote experiment state",
        )
        _schema(item["schema_version"], "remote experiment state")
        return cls(
            experiment_id=item["experiment_id"],  # type: ignore[arg-type]
            idempotency_key=item["idempotency_key"],  # type: ignore[arg-type]
            producer_id=item["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=item["producer_fingerprint"],  # type: ignore[arg-type]
            status=item["status"],  # type: ignore[arg-type]
            submitted_at_ms=item["submitted_at_ms"],  # type: ignore[arg-type]
            updated_at_ms=item["updated_at_ms"],  # type: ignore[arg-type]
            attempt_count=item["attempt_count"],  # type: ignore[arg-type]
            materials=_material_list(item["materials"], "state materials"),
        )

    @classmethod
    def unknown(
        cls,
        *,
        idempotency_key: str,
        producer_id: str,
        producer_fingerprint: str,
        experiment_id: str | None = None,
        attempt_count: int = 1,
        submitted_at_ms: int | None = None,
        updated_at_ms: int | None = None,
        materials: Sequence[RemoteMaterialReference] = (),
    ) -> RemoteExperimentState:
        return cls(
            experiment_id=experiment_id,
            idempotency_key=idempotency_key,
            producer_id=producer_id,
            producer_fingerprint=producer_fingerprint,
            status="unknown",
            submitted_at_ms=submitted_at_ms,
            updated_at_ms=updated_at_ms,
            attempt_count=attempt_count,
            materials=tuple(materials),
        )


def _state(value: object) -> RemoteExperimentState:
    if not isinstance(value, RemoteExperimentState):
        _fail("backend must return a RemoteExperimentState")
    return value


def _require_actionable(state: RemoteExperimentState, action: str) -> None:
    _state(state)
    if state.terminal:
        _fail(f"cannot {action} terminal remote experiment in state {state.status}")


def _same_reference(request: RemoteExperimentReference, state: RemoteExperimentState) -> None:
    if request.idempotency_key != state.idempotency_key:
        _fail("remote request idempotency_key does not match current state")
    if request.experiment_id != state.experiment_id:
        _fail("remote request experiment_id does not match current state")
    if request.producer_id != state.producer_id:
        _fail("remote request producer_id does not match current state")
    if request.producer_fingerprint != state.producer_fingerprint:
        _fail("remote request producer_fingerprint does not match current state")


def _material_map(
    values: Sequence[RemoteMaterialReference],
) -> dict[str, RemoteMaterialReference]:
    return {item.path: item for item in values}


def reconcile_remote_state(
    previous: RemoteExperimentState, observed: RemoteExperimentState
) -> RemoteExperimentState:
    """Validate one backend observation without inventing a remote terminal outcome.

    Repeated observations are idempotent.  An unknown state with no remote ID may learn that ID only
    while remaining unknown; a later observation can then reconcile it to running/completed/failed.
    """

    previous = _state(previous)
    observed = _state(observed)
    if previous.idempotency_key != observed.idempotency_key:
        _fail("remote state idempotency_key changed during reconciliation")
    if previous.producer_id != observed.producer_id:
        _fail("remote state producer_id changed during reconciliation")
    if previous.producer_fingerprint != observed.producer_fingerprint:
        _fail("remote state producer_fingerprint changed during reconciliation")
    if previous.experiment_id is None:
        if previous.status != "unknown":
            _fail("only unknown state may lack an experiment_id")
        if observed.status != "unknown":
            _fail("unknown state without an experiment_id must first reconcile the remote ID")
    elif previous.experiment_id != observed.experiment_id:
        _fail("remote experiment_id changed during reconciliation")

    allowed = _ALLOWED_TRANSITIONS[previous.status]
    if observed.status not in allowed:
        _fail(f"illegal remote state transition: {previous.status} -> {observed.status}")

    if observed.attempt_count < previous.attempt_count:
        _fail("remote attempt_count must be monotonic")
    if (
        previous.submitted_at_ms is not None
        and observed.submitted_at_ms != previous.submitted_at_ms
    ):
        _fail("remote submitted_at_ms must remain immutable once observed")
    if previous.updated_at_ms is not None and (
        observed.updated_at_ms is None or observed.updated_at_ms < previous.updated_at_ms
    ):
        _fail("remote updated_at_ms must be monotonic once observed")

    previous_materials = _material_map(previous.materials)
    observed_materials = _material_map(observed.materials)
    if any(observed_materials.get(path) != material for path, material in previous_materials.items()):
        _fail("remote material references must be append-only and immutable")

    if previous.terminal and observed != previous:
        _fail("terminal remote state is immutable")
    return observed


@runtime_checkable
class RemoteEvolutionBackend(Protocol):
    """Optional remote lifecycle adapter; implementations are explicitly supplied by callers."""

    def submit(self, request: RemoteSubmitRequest) -> RemoteExperimentState:
        ...

    def status(self, request: RemoteStatusRequest) -> RemoteExperimentState:
        ...

    def sync(self, request: RemoteSyncRequest) -> RemoteExperimentState:
        ...

    def continue_experiment(self, request: RemoteContinueRequest) -> RemoteExperimentState:
        ...

    def cancel(self, request: RemoteCancelRequest) -> RemoteExperimentState:
        ...


def _unknown_after(state: RemoteExperimentState) -> RemoteExperimentState:
    if state.terminal:
        return state
    return RemoteExperimentState.unknown(
        experiment_id=state.experiment_id,
        idempotency_key=state.idempotency_key,
        producer_id=state.producer_id,
        producer_fingerprint=state.producer_fingerprint,
        attempt_count=min(MAX_REMOTE_ATTEMPTS, state.attempt_count + 1),
        submitted_at_ms=state.submitted_at_ms,
        updated_at_ms=state.updated_at_ms,
        materials=state.materials,
    )


def _invoke_once(
    operation: Callable[[], RemoteExperimentState], fallback: RemoteExperimentState
) -> RemoteExperimentState:
    try:
        observed = operation()
    except (TimeoutError, OSError):
        return fallback
    if observed is None:  # type: ignore[comparison-overlap]
        return fallback
    return _state(observed)


def submit(
    backend: RemoteEvolutionBackend, request: RemoteSubmitRequest
) -> RemoteExperimentState:
    """Call submit once and validate its initial state; uncertainty is represented, not retried."""

    if not isinstance(request, RemoteSubmitRequest):
        _fail("submit request must be a RemoteSubmitRequest")
    fallback = RemoteExperimentState.unknown(
        idempotency_key=request.idempotency_key,
        producer_id=request.producer_id,
        producer_fingerprint=request.producer_fingerprint,
        attempt_count=1,
        materials=request.materials,
    )
    observed = _invoke_once(lambda: backend.submit(request), fallback)
    if observed.idempotency_key != request.idempotency_key:
        _fail("submit response idempotency_key does not match request")
    if observed.producer_id != request.producer_id:
        _fail("submit response producer_id does not match request")
    if observed.producer_fingerprint != request.producer_fingerprint:
        _fail("submit response producer_fingerprint does not match request")
    if observed.status not in {"submitted", "running", "unknown"}:
        _fail("submit response has an invalid initial state")
    requested = _material_map(request.materials)
    returned = _material_map(observed.materials)
    if any(returned.get(path) != material for path, material in requested.items()):
        _fail("submit response omitted or changed submitted material")
    return observed


def status(
    backend: RemoteEvolutionBackend,
    request: RemoteStatusRequest,
    previous: RemoteExperimentState,
) -> RemoteExperimentState:
    """Read status once and reconcile it with the last accepted observation."""

    if not isinstance(request, RemoteStatusRequest):
        _fail("status request must be a RemoteStatusRequest")
    _same_reference(request.reference, previous)
    observed = _invoke_once(lambda: backend.status(request), _unknown_after(previous))
    return reconcile_remote_state(previous, observed)


def sync(
    backend: RemoteEvolutionBackend,
    request: RemoteSyncRequest,
    previous: RemoteExperimentState,
) -> RemoteExperimentState:
    """Read synchronized material references once; no returned material receives a local score."""

    if not isinstance(request, RemoteSyncRequest):
        _fail("sync request must be a RemoteSyncRequest")
    _same_reference(request.reference, previous)
    observed = _invoke_once(lambda: backend.sync(request), _unknown_after(previous))
    return reconcile_remote_state(previous, observed)


def continue_experiment(
    backend: RemoteEvolutionBackend,
    request: RemoteContinueRequest,
    previous: RemoteExperimentState,
) -> RemoteExperimentState:
    """Request more iterations once; terminal experiments are rejected before backend invocation."""

    if not isinstance(request, RemoteContinueRequest):
        _fail("continue request must be a RemoteContinueRequest")
    _require_actionable(previous, "continue")
    _same_reference(request.reference, previous)
    observed = _invoke_once(
        lambda: backend.continue_experiment(request), _unknown_after(previous)
    )
    return reconcile_remote_state(previous, observed)


def cancel(
    backend: RemoteEvolutionBackend,
    request: RemoteCancelRequest,
    previous: RemoteExperimentState,
) -> RemoteExperimentState:
    """Request cancellation once; terminal experiments are rejected before backend invocation."""

    if not isinstance(request, RemoteCancelRequest):
        _fail("cancel request must be a RemoteCancelRequest")
    _require_actionable(previous, "cancel")
    _same_reference(request.reference, previous)
    observed = _invoke_once(lambda: backend.cancel(request), _unknown_after(previous))
    return reconcile_remote_state(previous, observed)


__all__ = [
    "MAX_REMOTE_ATTEMPTS",
    "MAX_REMOTE_ITERATIONS",
    "MAX_REMOTE_MATERIALS",
    "MAX_REMOTE_MATERIAL_BYTES",
    "MAX_REMOTE_PAYLOAD_BYTES",
    "MAX_REMOTE_TIMESTAMP_MS",
    "MAX_REMOTE_TOTAL_MATERIAL_BYTES",
    "REMOTE_EVOLUTION_SCHEMA_VERSION",
    "REMOTE_LIFECYCLE_STATUSES",
    "REMOTE_TERMINAL_STATUSES",
    "RemoteCancelRequest",
    "RemoteContinueRequest",
    "RemoteEvolutionBackend",
    "RemoteEvolutionError",
    "RemoteExperimentReference",
    "RemoteExperimentState",
    "RemoteLifecycleStatus",
    "RemoteMaterialReference",
    "RemoteStatusRequest",
    "RemoteSubmitRequest",
    "RemoteSyncRequest",
    "cancel",
    "continue_experiment",
    "reconcile_remote_state",
    "status",
    "submit",
    "sync",
]
