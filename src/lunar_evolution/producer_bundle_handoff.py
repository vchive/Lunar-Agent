"""Read-only preparation of explicit producer multi-file groups.

A :class:`ProducerResultEnvelope` describes one producer run as a flat list of material files.
This adapter adds the small amount of grouping information needed by repository-oriented
producers.  Each explicit group is projected into the existing
:class:`~lunar_evolution.candidate_bundle.CandidateSourceBundle` contract and verified against
the producer material directory.  Preparation does not evaluate, stage, execute, or copy source
files and it does not alter the generic producer or seed protocols.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .algorithm import AlgorithmProblemContract
from .candidate_bundle import (
    MAX_CANDIDATE_BUNDLE_FILES,
    CandidateBundleError,
    CandidateSourceBundle,
    CandidateSourceFile,
    VerifiedCandidateSourceBundle,
    verify_candidate_source_bundle,
)
from .producer_handoff import (
    PRODUCER_COMPLETED_STATUS,
    PRODUCER_FINGERPRINT_REQUIRED,
    PRODUCER_MATERIAL_KIND,
    ProducerHandoffError,
    ProducerResultEnvelope,
    parse_producer_envelope,
)

# Grouping limits intentionally remain within the generic producer envelope and source-bundle
# bounds.  They are exported so callers can preflight without relying on implementation details.
MAX_PRODUCER_BUNDLE_GROUPS = 32
MAX_PRODUCER_BUNDLE_PATHS = MAX_CANDIDATE_BUNDLE_FILES

PRODUCER_BUNDLE_GROUP_INVALID = "producer_bundle_group_invalid"
PRODUCER_BUNDLE_GROUPS_INVALID = "producer_bundle_groups_invalid"
PRODUCER_BUNDLE_GROUPS_EMPTY = "producer_bundle_groups_empty"
PRODUCER_BUNDLE_GROUPS_TOO_MANY = "producer_bundle_groups_too_many"
PRODUCER_BUNDLE_ID_INVALID = "producer_bundle_id_invalid"
PRODUCER_BUNDLE_ID_DUPLICATE = "producer_bundle_id_duplicate"
PRODUCER_BUNDLE_ENTRYPOINT_INVALID = "producer_bundle_entrypoint_invalid"
PRODUCER_BUNDLE_PATH_INVALID = "producer_bundle_path_invalid"
PRODUCER_BUNDLE_PATH_DUPLICATE = "producer_bundle_path_duplicate"
PRODUCER_BUNDLE_PATH_UNDECLARED = "producer_bundle_path_undeclared"
PRODUCER_BUNDLE_PATH_REUSED = "producer_bundle_path_reused"
PRODUCER_BUNDLE_MATERIALS_EMPTY = "producer_bundle_materials_empty"
PRODUCER_BUNDLE_CONTRACT_INVALID = "producer_bundle_contract_invalid"
PRODUCER_BUNDLE_CONTRACT_MISMATCH = "producer_bundle_contract_mismatch"
PRODUCER_BUNDLE_ENVELOPE_INVALID = "producer_bundle_envelope_invalid"
PRODUCER_BUNDLE_STATUS_INVALID = "producer_bundle_status_invalid"
PRODUCER_BUNDLE_IDENTITY_MISMATCH = "producer_bundle_identity_mismatch"
PRODUCER_BUNDLE_KIND_UNSUPPORTED = "producer_bundle_kind_unsupported"
PRODUCER_BUNDLE_ROOT_UNSAFE = "producer_bundle_root_unsafe"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CREDENTIAL = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token)\s*[:=]\s*\S+)"
)


class ProducerBundleHandoffError(ProducerHandoffError):
    """A fixed-code grouping or preparation failure without source prose."""


def _raise(code: str) -> None:
    raise ProducerBundleHandoffError(code)


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _raise(code)
    return value


def _identifier(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or _CREDENTIAL.search(value)
    ):
        _raise(code)
    return value


def _path(value: object, code: str = PRODUCER_BUNDLE_PATH_INVALID) -> str:
    try:
        raw = os.fspath(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, RuntimeError):
        _raise(code)
    if not isinstance(raw, str) or not raw or len(raw) > 1024:
        _raise(code)
    if (
        "\\" in raw
        or ":" in raw
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw)
        or unicodedata.normalize("NFC", raw) != raw
        or _CREDENTIAL.search(raw)
    ):
        _raise(code)
    try:
        if len(raw.encode("utf-8")) > 1024:
            _raise(code)
    except UnicodeEncodeError:
        _raise(code)
    parts = raw.split("/")
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts):
        _raise(code)
    if Path(raw).is_absolute():
        _raise(code)
    return raw


def _normalize_group(value: object) -> BundleGroup:
    if type(value) is not BundleGroup:
        _raise(PRODUCER_BUNDLE_GROUP_INVALID)
    try:
        paths = tuple(value.material_paths)
        return BundleGroup(value.bundle_id, value.entrypoint, paths)
    except ProducerBundleHandoffError:
        raise
    except Exception:  # noqa: BLE001 - DTO fields are untrusted at this boundary
        _raise(PRODUCER_BUNDLE_GROUP_INVALID)


@dataclass(frozen=True, slots=True)
class BundleGroup:
    """An explicit mapping from one producer bundle ID to material paths."""

    bundle_id: str
    entrypoint: str
    material_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, PRODUCER_BUNDLE_ID_INVALID)
        entrypoint = _path(self.entrypoint, PRODUCER_BUNDLE_ENTRYPOINT_INVALID)
        object.__setattr__(self, "entrypoint", entrypoint)
        if isinstance(self.material_paths, (str, bytes)) or not isinstance(
            self.material_paths, (tuple, list)
        ):
            _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        try:
            paths = tuple(self.material_paths)
        except (TypeError, RecursionError):
            _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        if not 1 <= len(paths) <= MAX_PRODUCER_BUNDLE_PATHS:
            _raise(PRODUCER_BUNDLE_MATERIALS_EMPTY if not paths else PRODUCER_BUNDLE_GROUP_INVALID)
        normalized = tuple(_path(item) for item in paths)
        if len(set(normalized)) != len(normalized):
            _raise(PRODUCER_BUNDLE_PATH_DUPLICATE)
        if entrypoint not in normalized:
            _raise(PRODUCER_BUNDLE_ENTRYPOINT_INVALID)
        object.__setattr__(self, "material_paths", normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "entrypoint": self.entrypoint,
            "material_paths": list(self.material_paths),
        }


@dataclass(frozen=True, slots=True)
class VerifiedProducerBundle:
    """Verified metadata for one explicit producer group.

    ``bundle`` is the canonical :class:`CandidateSourceBundle`; no source bytes are retained.
    The additional producer fields are provenance only and do not become a seed identity or score.
    """

    bundle_id: str
    bundle: CandidateSourceBundle
    bundle_sha256: str
    file_count: int
    total_bytes: int
    producer_fingerprint: str
    producer_id: str | None = None
    envelope_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, PRODUCER_BUNDLE_ID_INVALID)
        if not isinstance(self.bundle, CandidateSourceBundle):
            _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        _digest(self.bundle_sha256, PRODUCER_BUNDLE_GROUP_INVALID)
        if type(self.file_count) is not int or self.file_count != len(self.bundle.files):
            _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        if (
            type(self.total_bytes) is not int
            or self.total_bytes != sum(item.size for item in self.bundle.files)
        ):
            _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        _digest(self.producer_fingerprint, PRODUCER_FINGERPRINT_REQUIRED)
        if self.producer_id is not None:
            _identifier(self.producer_id, PRODUCER_BUNDLE_ID_INVALID)
        if self.envelope_sha256 is not None:
            _digest(self.envelope_sha256, PRODUCER_BUNDLE_GROUP_INVALID)

    @property
    def verified_bundle(self) -> VerifiedCandidateSourceBundle:
        return VerifiedCandidateSourceBundle(
            self.bundle, self.bundle_sha256, self.file_count, self.total_bytes,
        )

    @property
    def verified(self) -> VerifiedCandidateSourceBundle:
        """Compatibility spelling for callers that use the generic verifier result name."""

        return self.verified_bundle

    @property
    def source_bundle(self) -> CandidateSourceBundle:
        return self.bundle

    @property
    def entrypoint(self) -> str:
        return self.bundle.entrypoint

    @property
    def contract_sha256(self) -> str:
        return self.bundle.contract_sha256

    @property
    def material_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.bundle.files)

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "bundle": self.bundle.to_dict(),
            "bundle_sha256": self.bundle_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "producer_fingerprint": self.producer_fingerprint,
            "producer_id": self.producer_id,
            "envelope_sha256": self.envelope_sha256,
        }


# A descriptive alias for callers that prefer the result-oriented name used by other handoffs.
ProducerBundleResult = VerifiedProducerBundle
VerifiedBundleResult = VerifiedProducerBundle
VerifiedProducerBundleResult = VerifiedProducerBundle


def _normalize_envelope(value: object) -> ProducerResultEnvelope:
    try:
        if type(value) is ProducerResultEnvelope:
            raw = value.to_dict()
            envelope = ProducerResultEnvelope.from_dict(raw)
            if raw != envelope.to_dict():
                _raise(PRODUCER_BUNDLE_ENVELOPE_INVALID)
            return envelope
        if isinstance(value, Mapping):
            return parse_producer_envelope(value)
    except ProducerBundleHandoffError:
        raise
    except ProducerHandoffError:
        _raise(PRODUCER_BUNDLE_ENVELOPE_INVALID)
    except Exception:  # noqa: BLE001 - caller DTO/mapping is untrusted
        _raise(PRODUCER_BUNDLE_ENVELOPE_INVALID)
    _raise(PRODUCER_BUNDLE_ENVELOPE_INVALID)


def _contract_digest(contract: object) -> str:
    if not isinstance(contract, AlgorithmProblemContract):
        _raise(PRODUCER_BUNDLE_CONTRACT_INVALID)
    try:
        digest = contract.digest()
    except Exception:  # noqa: BLE001 - caller contract is a trust boundary
        _raise(PRODUCER_BUNDLE_CONTRACT_INVALID)
    return _digest(digest, PRODUCER_BUNDLE_CONTRACT_INVALID)


def _normalize_groups(value: object) -> tuple[BundleGroup, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _raise(PRODUCER_BUNDLE_GROUPS_INVALID)
    try:
        groups = tuple(value)
    except (TypeError, RecursionError):
        _raise(PRODUCER_BUNDLE_GROUPS_INVALID)
    if not groups:
        _raise(PRODUCER_BUNDLE_GROUPS_EMPTY)
    if len(groups) > MAX_PRODUCER_BUNDLE_GROUPS:
        _raise(PRODUCER_BUNDLE_GROUPS_TOO_MANY)
    normalized = tuple(_normalize_group(item) for item in groups)
    ids = [item.bundle_id for item in normalized]
    if len(ids) != len(set(ids)):
        _raise(PRODUCER_BUNDLE_ID_DUPLICATE)
    used: set[str] = set()
    for group in normalized:
        overlap = used.intersection(group.material_paths)
        if overlap:
            _raise(PRODUCER_BUNDLE_PATH_REUSED)
        used.update(group.material_paths)
    return normalized


def prepare_producer_bundle_manifest(
    external_root: str | os.PathLike[str],
    envelope: ProducerResultEnvelope | Mapping[str, object],
    groups: Sequence[BundleGroup],
    contract: AlgorithmProblemContract,
    producer_fingerprint: str,
    producer_id: str | None = None,
) -> tuple[VerifiedProducerBundle, ...]:
    """Verify explicit producer groups and return canonical bundle result DTOs.

    The function only reads declared source files.  It requires a completed generic producer
    envelope whose contract and producer pins match the caller's pins.  Group paths must name
    ``candidate_source`` materials from that envelope; ungrouped envelope materials are ignored.
    """

    contract_sha256 = _contract_digest(contract)
    _digest(producer_fingerprint, PRODUCER_FINGERPRINT_REQUIRED)
    if producer_id is not None:
        _identifier(producer_id, PRODUCER_BUNDLE_ID_INVALID)
    normalized_envelope = _normalize_envelope(envelope)
    normalized_groups = _normalize_groups(groups)

    if normalized_envelope.status != PRODUCER_COMPLETED_STATUS:
        _raise(PRODUCER_BUNDLE_STATUS_INVALID)
    if normalized_envelope.contract_sha256 != contract_sha256:
        _raise(PRODUCER_BUNDLE_CONTRACT_MISMATCH)
    if normalized_envelope.producer_fingerprint != producer_fingerprint or (
        producer_id is not None and normalized_envelope.producer_id != producer_id
    ):
        _raise(PRODUCER_BUNDLE_IDENTITY_MISMATCH)

    # Keep every declared path indexed so a grouped auxiliary artifact gets a fixed kind error;
    # ungrouped auxiliary materials remain producer-owned and are intentionally ignored.
    materials = {material.path: material for material in normalized_envelope.materials}

    results: list[VerifiedProducerBundle] = []
    for group in normalized_groups:
        descriptors: list[CandidateSourceFile] = []
        for path in group.material_paths:
            material = materials.get(path)
            if material is None:
                _raise(PRODUCER_BUNDLE_PATH_UNDECLARED)
            if material.kind != PRODUCER_MATERIAL_KIND:
                _raise(PRODUCER_BUNDLE_KIND_UNSUPPORTED)
            try:
                descriptors.append(CandidateSourceFile(path, material.size, material.sha256))
            except CandidateBundleError:
                # Candidate bundle path/digest checks are already fixed and path-free.
                raise
            except Exception:  # noqa: BLE001 - producer material fields are untrusted
                _raise(PRODUCER_BUNDLE_GROUP_INVALID)
        try:
            bundle = CandidateSourceBundle(contract_sha256, group.entrypoint, tuple(descriptors))
            verified = verify_candidate_source_bundle(
                bundle,
                source_root=external_root,
                contract_sha256=contract_sha256,
            )
        except CandidateBundleError:
            raise
        except (OSError, TypeError, ValueError, RuntimeError):
            _raise(PRODUCER_BUNDLE_ROOT_UNSAFE)
        results.append(
            VerifiedProducerBundle(
                bundle_id=group.bundle_id,
                bundle=verified.bundle,
                bundle_sha256=verified.bundle_sha256,
                file_count=verified.file_count,
                total_bytes=verified.total_bytes,
                producer_fingerprint=producer_fingerprint,
                producer_id=normalized_envelope.producer_id,
                envelope_sha256=normalized_envelope.envelope_sha256,
            )
        )
    return tuple(results)


__all__ = [
    "MAX_PRODUCER_BUNDLE_GROUPS",
    "MAX_PRODUCER_BUNDLE_PATHS",
    "PRODUCER_BUNDLE_CONTRACT_INVALID",
    "PRODUCER_BUNDLE_CONTRACT_MISMATCH",
    "PRODUCER_BUNDLE_ENTRYPOINT_INVALID",
    "PRODUCER_BUNDLE_ENVELOPE_INVALID",
    "PRODUCER_BUNDLE_GROUPS_EMPTY",
    "PRODUCER_BUNDLE_GROUPS_INVALID",
    "PRODUCER_BUNDLE_GROUPS_TOO_MANY",
    "PRODUCER_BUNDLE_GROUP_INVALID",
    "PRODUCER_BUNDLE_IDENTITY_MISMATCH",
    "PRODUCER_BUNDLE_ID_DUPLICATE",
    "PRODUCER_BUNDLE_ID_INVALID",
    "PRODUCER_BUNDLE_KIND_UNSUPPORTED",
    "PRODUCER_BUNDLE_MATERIALS_EMPTY",
    "PRODUCER_BUNDLE_PATH_DUPLICATE",
    "PRODUCER_BUNDLE_PATH_INVALID",
    "PRODUCER_BUNDLE_PATH_REUSED",
    "PRODUCER_BUNDLE_PATH_UNDECLARED",
    "PRODUCER_BUNDLE_ROOT_UNSAFE",
    "PRODUCER_BUNDLE_STATUS_INVALID",
    "BundleGroup",
    "ProducerBundleHandoffError",
    "ProducerBundleResult",
    "VerifiedBundleResult",
    "VerifiedProducerBundle",
    "VerifiedProducerBundleResult",
    "prepare_producer_bundle_manifest",
]
