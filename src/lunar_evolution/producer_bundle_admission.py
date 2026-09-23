"""Deterministic admission descriptors for explicit producer bundle batches.

This boundary records what a caller intends to admit before any local execution or archive
publication.  It binds the verified producer-bundle projection to the local contract and
execution authority, while keeping producer evidence outside candidate score and identity.
The descriptor is deliberately provider-free and read-only; a later transaction can use its
digest to make archive publication and resume checks fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_bundle import CandidateBundleError, CandidateSourceBundle, CandidateSourceFile
from .candidate_evaluation_spec import strict_json
from .evolution import CandidateDraft
from .producer_bundle_handoff import (
    MAX_PRODUCER_BUNDLE_GROUPS,
    ProducerBundleHandoffError,
)
from .producer_bundle_handoff import _identifier as _producer_identifier
from .producer_bundle_handoff import _path as _producer_path
from .producer_bundle_population import ProducerBundleDraft

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = "1"
_PROTOCOL = "lunar-producer-bundle-admission-v1"
_MAX_BUNDLES = MAX_PRODUCER_BUNDLE_GROUPS
MAX_PRODUCER_BUNDLE_ADMISSION_BYTES = 128 * 1024
_ITEM_FIELDS = {
    "bundle_id", "bundle_sha256", "draft_bundle_sha256", "entrypoint", "material_paths",
    "producer_fingerprint", "producer_id", "envelope_sha256",
}
_PLAN_FIELDS = {
    "schema_version", "protocol", "contract_sha256", "evaluator_kind",
    "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256",
    "environment_sha256", "bundles",
}


class ProducerBundleAdmissionError(ValueError):
    """Fixed-code admission descriptor failure without producer-controlled prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundleAdmissionError(code)


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str) -> str:
    try:
        return _producer_identifier(value, code)
    except ProducerBundleHandoffError:
        _fail(code)


def _canonical(value: object) -> bytes:
    try:
        content = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ProducerBundleAdmissionError("producer_bundle_admission_canonical_invalid") from exc
    if len(content) > MAX_PRODUCER_BUNDLE_ADMISSION_BYTES:
        _fail("producer_bundle_admission_too_large")
    return content


def _object(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("producer_bundle_admission_schema_invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProducerBundleAdmissionItem:
    """One producer bundle bound to its native draft and producer provenance."""

    bundle_id: str
    bundle_sha256: str
    draft_bundle_sha256: str
    entrypoint: str
    material_paths: tuple[str, ...]
    producer_fingerprint: str
    producer_id: str | None = None
    envelope_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, "producer_bundle_admission_id_invalid")
        _digest(self.bundle_sha256, "producer_bundle_admission_bundle_digest_invalid")
        _digest(self.draft_bundle_sha256, "producer_bundle_admission_draft_digest_invalid")
        _digest(self.producer_fingerprint, "producer_bundle_admission_identity_invalid")
        if (
            isinstance(self.material_paths, (str, bytes))
            or not isinstance(self.material_paths, tuple)
            or not self.material_paths
            or any(not isinstance(path, str) or not path for path in self.material_paths)
            or len(set(self.material_paths)) != len(self.material_paths)
            or self.entrypoint not in self.material_paths
        ):
            _fail("producer_bundle_admission_paths_invalid")
        try:
            # Reuse the canonical source protocol for bounds and path/case collisions. These
            # empty descriptors validate names only; they do not claim to validate source bytes.
            names = CandidateSourceBundle(
                "0" * 64, _producer_path(self.entrypoint),
                tuple(CandidateSourceFile(_producer_path(path), 0, "0" * 64)
                      for path in self.material_paths),
            )
        except (CandidateBundleError, ProducerBundleHandoffError):
            _fail("producer_bundle_admission_paths_invalid")
        object.__setattr__(self, "material_paths", tuple(item.path for item in names.files))
        if self.bundle_sha256 != self.draft_bundle_sha256:
            _fail("producer_bundle_admission_bundle_mismatch")
        if self.producer_id is not None:
            _identifier(self.producer_id, "producer_bundle_admission_producer_id_invalid")
        if self.envelope_sha256 is not None:
            _digest(self.envelope_sha256, "producer_bundle_admission_envelope_digest_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "bundle_sha256": self.bundle_sha256,
            "draft_bundle_sha256": self.draft_bundle_sha256,
            "entrypoint": self.entrypoint,
            "material_paths": list(self.material_paths),
            "producer_fingerprint": self.producer_fingerprint,
            "producer_id": self.producer_id,
            "envelope_sha256": self.envelope_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleAdmissionItem:
        raw = _object(value, _ITEM_FIELDS)
        if not isinstance(raw["material_paths"], list):
            _fail("producer_bundle_admission_paths_invalid")
        return cls(**{**raw, "material_paths": tuple(raw["material_paths"])})


@dataclass(frozen=True, slots=True)
class ProducerBundleAdmissionPlan:
    """Canonical, provider-free descriptor for one explicit bundle admission batch."""

    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    runner_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    bundles: tuple[ProducerBundleAdmissionItem, ...]
    schema_version: str = _SCHEMA_VERSION
    protocol: str = _PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION or self.protocol != _PROTOCOL:
            _fail("producer_bundle_admission_schema_invalid")
        _identifier(self.evaluator_kind, "producer_bundle_admission_evaluator_invalid")
        for value, code in (
            (self.contract_sha256, "producer_bundle_admission_contract_invalid"),
            (self.evaluator_fingerprint, "producer_bundle_admission_evaluator_invalid"),
            (self.runner_fingerprint, "producer_bundle_admission_runner_invalid"),
            (self.dependency_sha256, "producer_bundle_admission_dependency_invalid"),
            (self.environment_sha256, "producer_bundle_admission_environment_invalid"),
        ):
            _digest(value, code)
        if (
            not isinstance(self.bundles, tuple)
            or not 1 <= len(self.bundles) <= _MAX_BUNDLES
            or any(not isinstance(item, ProducerBundleAdmissionItem) for item in self.bundles)
        ):
            _fail("producer_bundle_admission_bundles_invalid")
        try:
            # Frozen dataclasses are shallow: rebuild nested values at every trust boundary.
            normalized = tuple(ProducerBundleAdmissionItem.from_dict(item.to_dict())
                               for item in self.bundles)
        except ProducerBundleAdmissionError:
            raise
        except Exception as exc:
            raise ProducerBundleAdmissionError("producer_bundle_admission_bundles_invalid") from exc
        object.__setattr__(self, "bundles", normalized)
        ids = [item.bundle_id for item in self.bundles]
        if len(ids) != len(set(ids)):
            _fail("producer_bundle_admission_id_duplicate")
        paths = [path for item in self.bundles for path in item.material_paths]
        if len(paths) != len(set(paths)):
            _fail("producer_bundle_admission_path_reused")
        _canonical(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "runner_fingerprint": self.runner_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "bundles": [item.to_dict() for item in self.bundles],
        }

    def digest(self) -> str:
        try:
            normalized = parse_producer_bundle_admission_plan(self.to_dict())
            return hashlib.sha256(_canonical(normalized.to_dict())).hexdigest()
        except ProducerBundleAdmissionError:
            raise
        except Exception as exc:
            raise ProducerBundleAdmissionError("producer_bundle_admission_plan_invalid") from exc

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleAdmissionPlan:
        raw = _object(value, _PLAN_FIELDS)
        if not isinstance(raw["bundles"], list) or not 1 <= len(raw["bundles"]) <= _MAX_BUNDLES:
            _fail("producer_bundle_admission_bundles_invalid")
        return cls(**{**raw, "bundles": tuple(
            ProducerBundleAdmissionItem.from_dict(item) for item in raw["bundles"]
        )})


def _draft_bundle_digest(draft: CandidateDraft, contract_sha256: str) -> str:
    if draft.source_files is None:
        _fail("producer_bundle_admission_draft_invalid")
    try:
        from .bundle_evolution import validate_bundle_draft

        return validate_bundle_draft(draft, contract_sha256).digest()
    except ProducerBundleAdmissionError:
        raise
    except Exception as exc:
        raise ProducerBundleAdmissionError("producer_bundle_admission_draft_invalid") from exc


def build_producer_bundle_admission_plan(
    drafts: tuple[ProducerBundleDraft, ...] | list[ProducerBundleDraft],
    *,
    contract_sha256: str,
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
) -> ProducerBundleAdmissionPlan:
    """Bind verified producer drafts to local execution authority without side effects.

    The input order is retained because callers may assign bundles to islands by order.  The
    resulting digest is suitable for a future archive admission journal and resume comparison.
    """

    if isinstance(drafts, (str, bytes)) or not isinstance(drafts, (tuple, list)):
        _fail("producer_bundle_admission_bundles_invalid")
    if not 1 <= len(drafts) <= _MAX_BUNDLES:
        _fail("producer_bundle_admission_bundles_invalid")
    contract_sha256 = _digest(contract_sha256, "producer_bundle_admission_contract_invalid")
    evaluator_kind = _identifier(evaluator_kind, "producer_bundle_admission_evaluator_invalid")
    evaluator_fingerprint = _digest(evaluator_fingerprint, "producer_bundle_admission_evaluator_invalid")
    runner_fingerprint = _digest(runner_fingerprint, "producer_bundle_admission_runner_invalid")
    dependency_sha256 = _digest(dependency_sha256, "producer_bundle_admission_dependency_invalid")
    environment_sha256 = _digest(environment_sha256, "producer_bundle_admission_environment_invalid")
    items: list[ProducerBundleAdmissionItem] = []
    for value in drafts:
        if not isinstance(value, ProducerBundleDraft):
            _fail("producer_bundle_admission_draft_invalid")
        try:
            # Detach caller-owned mutable maps before deriving paths, digest and provenance.
            if not isinstance(value.draft, CandidateDraft) or value.draft.source_files is None:
                _fail("producer_bundle_admission_draft_invalid")
            if not isinstance(value.draft.metadata, dict):
                _fail("producer_bundle_admission_provenance_invalid")
            metadata = json.loads(_canonical(value.draft.metadata))
            draft = CandidateDraft(
                value.draft.source, value.draft.filename, metadata, dict(value.draft.source_files),
            )
            value = ProducerBundleDraft(
                value.bundle_id, draft, value.bundle_sha256, value.producer_fingerprint,
                value.producer_id, value.envelope_sha256,
            )
        except ProducerBundleAdmissionError:
            raise
        except Exception as exc:
            raise ProducerBundleAdmissionError("producer_bundle_admission_draft_invalid") from exc
        draft_digest = _draft_bundle_digest(draft, contract_sha256)
        expected = {
            "bundle_id": value.bundle_id,
            "bundle_sha256": value.bundle_sha256,
            "producer_fingerprint": value.producer_fingerprint,
            "producer_id": value.producer_id,
            "envelope_sha256": value.envelope_sha256,
        }
        if metadata != {"producer_bundle": expected}:
            _fail("producer_bundle_admission_provenance_invalid")
        if draft_digest != value.bundle_sha256:
            _fail("producer_bundle_admission_bundle_mismatch")
        items.append(
            ProducerBundleAdmissionItem(
                bundle_id=value.bundle_id,
                bundle_sha256=value.bundle_sha256,
                draft_bundle_sha256=draft_digest,
                entrypoint=draft.filename,
                material_paths=tuple(sorted(draft.source_files)),
                producer_fingerprint=value.producer_fingerprint,
                producer_id=value.producer_id,
                envelope_sha256=value.envelope_sha256,
            )
        )
    try:
        return ProducerBundleAdmissionPlan(
            contract_sha256=contract_sha256,
            evaluator_kind=evaluator_kind,
            evaluator_fingerprint=evaluator_fingerprint,
            runner_fingerprint=runner_fingerprint,
            dependency_sha256=dependency_sha256,
            environment_sha256=environment_sha256,
            bundles=tuple(items),
        )
    except ProducerBundleAdmissionError:
        raise
    except Exception as exc:
        raise ProducerBundleAdmissionError("producer_bundle_admission_plan_invalid") from exc


def parse_producer_bundle_admission_plan(
    source: Mapping[str, object] | str | os.PathLike[str],
) -> ProducerBundleAdmissionPlan:
    """Read a bounded descriptor; parsing does not verify sources or admit execution.

    A later consumer must compare the digest to independent caller pins and rebuild the plan
    from the candidate drafts and execution profile before treating it as a matching intent.
    """
    try:
        if isinstance(source, Mapping):
            raw = strict_json(_canonical(dict(source)), MAX_PRODUCER_BUNDLE_ADMISSION_BYTES)
        else:
            try:
                content = _files.read_regular_file(
                    _files.absolute_path(source), MAX_PRODUCER_BUNDLE_ADMISSION_BYTES,
                )
            except _files.BenchmarkFileError as exc:
                if exc.reason == "too_large":
                    _fail("producer_bundle_admission_too_large")
                raise
            raw = strict_json(content, MAX_PRODUCER_BUNDLE_ADMISSION_BYTES)
        return ProducerBundleAdmissionPlan.from_dict(raw)
    except ProducerBundleAdmissionError:
        raise
    except Exception as exc:
        raise ProducerBundleAdmissionError("producer_bundle_admission_plan_invalid") from exc


__all__ = [
    "MAX_PRODUCER_BUNDLE_ADMISSION_BYTES",
    "ProducerBundleAdmissionError",
    "ProducerBundleAdmissionItem",
    "ProducerBundleAdmissionPlan",
    "build_producer_bundle_admission_plan",
    "parse_producer_bundle_admission_plan",
]
