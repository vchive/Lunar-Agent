"""Convert completed remote material observations into local producer admission.

The remote lifecycle module intentionally stops at score-free material references.  This adapter
is the next boundary: it accepts a reconciled completed observation, builds the existing generic
producer envelope in memory, and sends the referenced local files through the same exact-harness
admission path used by OpenEvolve and ShinkaEvolve.  It never calls a backend, downloads a file,
trusts a remote score, or mutates the synchronized material root.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .algorithm import AlgorithmProblemContract
from .producer_handoff import (
    MAX_PRODUCER_BUDGET_FIELDS,
    MAX_PRODUCER_BUDGET_VALUE,
    PRODUCER_MATERIAL_KIND,
    ProducerHandoffError,
    ProducerMaterial,
    ProducerResultEnvelope,
    admit_producer_envelope,
)
from .remote_evolution import (
    MAX_REMOTE_MATERIALS,
    RemoteEvolutionError,
    RemoteExperimentState,
    RemoteMaterialReference,
    reconcile_remote_state,
)
from .seed_handoff import SeedAdmissionResult

REMOTE_MATERIAL_HANDOFF_PROTOCOL = "lunar-remote-material-handoff-v1"

REMOTE_HANDOFF_STATE_INVALID = "remote_handoff_state_invalid"
REMOTE_HANDOFF_NOT_COMPLETED = "remote_handoff_not_completed"
REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED = "remote_handoff_experiment_id_required"
REMOTE_HANDOFF_MATERIALS_EMPTY = "remote_handoff_materials_empty"
REMOTE_HANDOFF_IDENTITY_MISMATCH = "remote_handoff_identity_mismatch"
REMOTE_HANDOFF_RECONCILIATION_INVALID = "remote_handoff_reconciliation_invalid"
REMOTE_HANDOFF_MATERIAL_KIND_UNSUPPORTED = "remote_handoff_material_kind_unsupported"
REMOTE_HANDOFF_BUDGET_INVALID = "remote_handoff_budget_invalid"
REMOTE_HANDOFF_CONTRACT_INVALID = "remote_handoff_contract_invalid"
REMOTE_HANDOFF_STAGING_ROOT_UNSAFE = "remote_handoff_staging_root_unsafe"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REMOTE_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_BUDGET_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class RemoteMaterialHandoffError(ProducerHandoffError):
    """A fixed-code remote material conversion failure."""


def _raise(code: str) -> None:
    raise RemoteMaterialHandoffError(code)


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _raise(code)
    return value


def _contract_digest(contract: AlgorithmProblemContract) -> str:
    """Read a contract digest without allowing a malformed object to cross this boundary."""

    if not isinstance(contract, AlgorithmProblemContract):
        _raise(REMOTE_HANDOFF_CONTRACT_INVALID)
    try:
        digest = contract.digest()
    except Exception:  # noqa: BLE001 - a caller supplied contract is untrusted at this boundary
        _raise(REMOTE_HANDOFF_CONTRACT_INVALID)
    return _digest(digest, REMOTE_HANDOFF_CONTRACT_INVALID)


def _budget_copy(value: object) -> dict[str, int | float]:
    """Detach and bound a caller mapping before constructing the producer envelope.

    ``Mapping`` is intentionally accepted in the public signature, but arbitrary mapping
    implementations can raise while iterating or converting with ``dict(value)``.  Iterating at
    most one field beyond the protocol limit keeps those failures inside the fixed remote error
    boundary and avoids an unbounded custom iterator.
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        _raise(REMOTE_HANDOFF_BUDGET_INVALID)
    result: dict[str, int | float] = {}
    try:
        iterator = iter(value)
        for _ in range(MAX_PRODUCER_BUDGET_FIELDS + 1):
            try:
                key = next(iterator)
            except StopIteration:
                break
            if not isinstance(key, str) or _BUDGET_KEY.fullmatch(key) is None:
                _raise(REMOTE_HANDOFF_BUDGET_INVALID)
            if key in result:
                _raise(REMOTE_HANDOFF_BUDGET_INVALID)
            item = value[key]
            if type(item) not in (int, float):
                _raise(REMOTE_HANDOFF_BUDGET_INVALID)
            try:
                finite = math.isfinite(float(item))
            except (OverflowError, TypeError, ValueError):
                _raise(REMOTE_HANDOFF_BUDGET_INVALID)
            if not finite or item < 0 or item > MAX_PRODUCER_BUDGET_VALUE:
                _raise(REMOTE_HANDOFF_BUDGET_INVALID)
            result[key] = item
        else:
            # The loop exhausted its bounded budget without seeing StopIteration.
            _raise(REMOTE_HANDOFF_BUDGET_INVALID)
    except RemoteMaterialHandoffError:
        raise
    except Exception:  # noqa: BLE001 - custom Mapping implementations are untrusted
        _raise(REMOTE_HANDOFF_BUDGET_INVALID)
    if not result:
        _raise(REMOTE_HANDOFF_BUDGET_INVALID)
    return result


def _run_id(experiment_id: str) -> str:
    """Keep a remote ID as provenance without widening producer identifier syntax."""

    if _SAFE_RUN_ID.fullmatch(experiment_id):
        return experiment_id
    digest = hashlib.sha256(experiment_id.encode("utf-8")).hexdigest()
    return f"remote-{digest}"


def _canonical_path(value: str | Path) -> Path:
    """Return a resolved path used only for root-overlap checks.

    The generic seed adapter creates ``staging_root`` when it is supplied.  Before delegating,
    compare resolved paths so that this bridge cannot create a temporary directory inside (or
    through an alias of) the synchronized material root.  Standard platform aliases such as
    macOS's ``/var`` link are allowed; a final staging symlink is still rejected by the generic
    adapter before it creates anything.
    """

    try:
        raw = Path(value).expanduser()
        absolute = Path(os.path.abspath(raw))
        return absolute.resolve(strict=False)
    except RemoteMaterialHandoffError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)


def _existing_ancestors(path: Path) -> tuple[Path, ...]:
    """Return existing path components, including a possibly aliased leaf.

    ``Path.resolve(strict=False)`` normalizes symlinks but cannot normalize the spelling of a
    path on a case-insensitive filesystem when the final component does not exist yet.  The
    staging directory is intentionally allowed to be created later, so retain existing ancestors
    and compare their filesystem identities with ``samefile`` below.
    """

    result: list[Path] = []
    current = path
    while True:
        try:
            if os.path.lexists(current):
                result.append(current)
        except (OSError, TypeError, ValueError):
            pass
        parent = current.parent
        if parent == current:
            break
        current = parent
    return tuple(result)


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (OSError, TypeError, ValueError):
        return False


def _ensure_staging_disjoint(material_root: str | Path, staging_root: str | Path | None) -> None:
    if staging_root is None:
        return
    try:
        raw_staging = Path(staging_root).expanduser()
        if raw_staging.is_symlink():
            _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)
    except RemoteMaterialHandoffError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)
    material_path = _canonical_path(material_root)
    staging_path = _canonical_path(staging_root)
    # Reject either ancestor/descendant relationship. Keeping the staging tree wholly separate
    # from the synchronized tree makes the bridge's read-only material-root guarantee explicit;
    # sibling directories remain valid and are the recommended arrangement.
    if (
        staging_path == material_path
        or material_path in staging_path.parents
        or staging_path in material_path.parents
    ):
        _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)

    # ``Path`` ancestry compares path text. On case-insensitive filesystems a spelling such as
    # ``MaterialRoot`` versus ``materialroot/nested`` can evade that check while the generic seed
    # adapter later creates the staging directory inside the synchronized tree. Compare both roots
    # with the existing ancestors of the other path by filesystem identity.
    staging_ancestors = _existing_ancestors(staging_path)
    if any(_same_file(material_path, ancestor) for ancestor in staging_ancestors):
        _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)
    material_ancestors = _existing_ancestors(material_path)
    if any(_same_file(staging_path, ancestor) for ancestor in material_ancestors):
        _raise(REMOTE_HANDOFF_STAGING_ROOT_UNSAFE)


def _state_evidence(state: RemoteExperimentState) -> dict[str, Any]:
    # RemoteExperimentState is already a strict, bounded score-free DTO.  Wrapping its canonical
    # projection in one evidence object lets ProducerResultEnvelope reduce it to a digest-only
    # summary before any seed metadata is persisted.
    return {
        "protocol": REMOTE_MATERIAL_HANDOFF_PROTOCOL,
        "remote_state": state.to_dict(),
    }


def _normalize_state(
    value: object,
    code: str,
) -> RemoteExperimentState:
    """Re-parse a DTO before relying on its frozen fields.

    ``dataclass(frozen=True)`` prevents ordinary mutation but does not protect a boundary from a
    caller that deliberately constructs an object with ``object.__new__``/``object.__setattr__``
    or supplies a subclass with overridden attributes.  A canonical round-trip reapplies every
    remote lifecycle bound (timestamps, attempts, material aggregate size, and payload size) and
    keeps malformed observations inside this adapter's fixed error vocabulary.
    """

    if not isinstance(value, RemoteExperimentState):
        _raise(code)
    if code == REMOTE_HANDOFF_STATE_INVALID:
        # Preserve the public, more specific error for the common terminal-without-ID case
        # before the full DTO round-trip rejects the same malformed observation.
        try:
            missing_completed_id = value.status == "completed" and value.experiment_id is None
        except Exception:  # noqa: BLE001 - continue with the generic fixed-code path below
            missing_completed_id = False
        if missing_completed_id:
            _raise(REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED)
    try:
        payload = value.to_dict()
        return RemoteExperimentState.from_dict(payload)
    except Exception:  # noqa: BLE001 - remote DTOs are untrusted boundary input
        _raise(code)


def _validate_state(
    state: RemoteExperimentState,
    *,
    contract_sha256: str,
    producer_id: str,
    producer_fingerprint: str,
    budget: Mapping[str, int | float],
    previous_state: RemoteExperimentState | None,
) -> tuple[
    RemoteExperimentState,
    str,
    tuple[RemoteMaterialReference, ...],
    dict[str, int | float],
]:
    state = _normalize_state(state, REMOTE_HANDOFF_STATE_INVALID)
    if previous_state is not None:
        previous_state = _normalize_state(
            previous_state,
            REMOTE_HANDOFF_RECONCILIATION_INVALID,
        )
        try:
            state = reconcile_remote_state(previous_state, state)
        except RemoteEvolutionError:
            _raise(REMOTE_HANDOFF_RECONCILIATION_INVALID)
        except Exception:  # noqa: BLE001 - malformed reconciliation input is untrusted
            _raise(REMOTE_HANDOFF_RECONCILIATION_INVALID)
    try:
        status = state.status
        experiment_id = state.experiment_id
        materials = state.materials
        state_producer_id = state.producer_id
        state_producer_fingerprint = state.producer_fingerprint
    except Exception:  # noqa: BLE001 - a forged DTO must not leak an implementation exception
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    if not isinstance(status, str):
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    if status != "completed":
        _raise(REMOTE_HANDOFF_NOT_COMPLETED)
    if experiment_id is None:
        _raise(REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED)
    if not isinstance(experiment_id, str) or _REMOTE_EXPERIMENT_ID.fullmatch(experiment_id) is None:
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    if type(materials) is not tuple:
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    if len(materials) > MAX_REMOTE_MATERIALS:
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    material_values = materials
    if not material_values:
        _raise(REMOTE_HANDOFF_MATERIALS_EMPTY)
    if any(type(item) is not RemoteMaterialReference for item in material_values):
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    try:
        identity_matches = (
            state_producer_id == producer_id
            and state_producer_fingerprint == producer_fingerprint
        )
    except Exception:  # noqa: BLE001 - forged DTO fields must remain fixed-code failures
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    if not identity_matches:
        _raise(REMOTE_HANDOFF_IDENTITY_MISMATCH)
    _digest(contract_sha256, REMOTE_HANDOFF_CONTRACT_INVALID)
    normalized_budget = _budget_copy(budget)
    return state, experiment_id, material_values, normalized_budget


def remote_state_to_producer_envelope(
    state: RemoteExperimentState,
    *,
    contract_sha256: str,
    producer_id: str,
    producer_fingerprint: str,
    budget: Mapping[str, int | float],
    previous_state: RemoteExperimentState | None = None,
) -> ProducerResultEnvelope:
    """Build a generic producer envelope from a pinned completed remote observation.

    The returned envelope contains only material digests and a normalized evidence summary.  It
    is not a local evaluation and cannot be ranked until passed to :func:`admit_remote_materials`.
    """

    state, experiment_id, references, normalized_budget = _validate_state(
        state,
        contract_sha256=contract_sha256,
        producer_id=producer_id,
        producer_fingerprint=producer_fingerprint,
        budget=budget,
        previous_state=previous_state,
    )
    materials: list[ProducerMaterial] = []
    for reference in references:
        try:
            if reference.kind != PRODUCER_MATERIAL_KIND:
                _raise(REMOTE_HANDOFF_MATERIAL_KIND_UNSUPPORTED)
            materials.append(
                ProducerMaterial(
                    kind=reference.kind,
                    path=reference.path,
                    size=reference.size,
                    sha256=reference.sha256,
                )
            )
        except RemoteMaterialHandoffError:
            raise
        except ProducerHandoffError:
            _raise(REMOTE_HANDOFF_STATE_INVALID)
        except Exception:  # noqa: BLE001 - forged reference fields are untrusted
            _raise(REMOTE_HANDOFF_STATE_INVALID)
    try:
        return ProducerResultEnvelope(
            schema_version="1",
            producer_id=producer_id,
            producer_fingerprint=producer_fingerprint,
            producer_run_id=_run_id(experiment_id),
            status="completed",
            contract_sha256=contract_sha256,
            budget=normalized_budget,
            materials=tuple(materials),
            external_evidence=_state_evidence(state),
        )
    except ProducerHandoffError as exc:
        if exc.code.startswith("producer_budget"):
            _raise(REMOTE_HANDOFF_BUDGET_INVALID)
        if exc.code == "producer_contract_mismatch":
            _raise(REMOTE_HANDOFF_CONTRACT_INVALID)
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    except Exception:  # noqa: BLE001 - malformed DTO projections must remain fixed-code
        _raise(REMOTE_HANDOFF_STATE_INVALID)


def admit_remote_materials(
    material_root: str | Path,
    state: RemoteExperimentState,
    contract: AlgorithmProblemContract,
    evaluator: Any,
    *,
    evaluator_fingerprint: str,
    producer_id: str,
    producer_fingerprint: str,
    budget: Mapping[str, int | float],
    previous_state: RemoteExperimentState | None = None,
    staging_root: str | Path | None = None,
    num_islands: int = 1,
) -> SeedAdmissionResult:
    """Admit synchronized remote material through Lunar's local exact evaluator.

    ``material_root`` is read by the existing producer adapter.  The adapter's descriptor-based
    checks verify each referenced regular file, size, digest, and confinement.  The remote backend
    is never invoked by this function.
    """

    contract_sha256 = _contract_digest(contract)
    if not callable(evaluator):
        _raise(REMOTE_HANDOFF_STATE_INVALID)
    envelope = remote_state_to_producer_envelope(
        state,
        contract_sha256=contract_sha256,
        producer_id=producer_id,
        producer_fingerprint=producer_fingerprint,
        budget=budget,
        previous_state=previous_state,
    )
    _ensure_staging_disjoint(material_root, staging_root)
    ref_overrides = {material.path: (material.path,) for material in envelope.materials}
    return admit_producer_envelope(
        material_root,
        envelope,
        contract,
        evaluator,
        evaluator_fingerprint=evaluator_fingerprint,
        producer_fingerprint=producer_fingerprint,
        producer_id=producer_id,
        staging_root=staging_root,
        num_islands=num_islands,
        material_ref_overrides=ref_overrides,
    )


# Friendly aliases for callers that describe the operation as an import or admission.
build_remote_producer_envelope = remote_state_to_producer_envelope
admit_remote_state = admit_remote_materials


__all__ = [
    "REMOTE_HANDOFF_BUDGET_INVALID",
    "REMOTE_HANDOFF_CONTRACT_INVALID",
    "REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED",
    "REMOTE_HANDOFF_IDENTITY_MISMATCH",
    "REMOTE_HANDOFF_MATERIALS_EMPTY",
    "REMOTE_HANDOFF_MATERIAL_KIND_UNSUPPORTED",
    "REMOTE_HANDOFF_NOT_COMPLETED",
    "REMOTE_HANDOFF_RECONCILIATION_INVALID",
    "REMOTE_HANDOFF_STAGING_ROOT_UNSAFE",
    "REMOTE_HANDOFF_STATE_INVALID",
    "REMOTE_MATERIAL_HANDOFF_PROTOCOL",
    "RemoteMaterialHandoffError",
    "admit_remote_materials",
    "admit_remote_state",
    "build_remote_producer_envelope",
    "remote_state_to_producer_envelope",
]
