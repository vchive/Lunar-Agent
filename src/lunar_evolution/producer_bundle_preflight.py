"""Read-only preflight for producer-bundle publication batches.

The preflight binds a Feature 152 admission plan to a Feature 153 journal and an existing
native population archive.  It derives the batch directory from the system workspace and journal
identity; callers cannot select a sibling path.  This module never creates files, executes source,
invokes providers, or mutates an archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_evaluation_spec import strict_json
from .evolution import (
    MAX_ARCHIVE_BYTES,
    MAX_STATE_BYTES,
    CandidateArchive,
    CandidateIntegrityAuthority,
    EvolutionError,
)
from .producer_bundle_admission import ProducerBundleAdmissionPlan
from .producer_bundle_publication import ProducerBundlePublicationJournal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SCHEMA_VERSION = "1"
_PROTOCOL = "lunar-producer-bundle-preflight-v1"
MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES = 128 * 1024


class ProducerBundlePreflightError(ValueError):
    """Fixed-code read-only preflight failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundlePreflightError(code)


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_canonical_invalid") from exc
    if len(encoded) > MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES:
        _fail("producer_bundle_preflight_too_large")
    return encoded


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("producer_bundle_preflight_schema_invalid")
    return value


def _safe_workspace(value: object) -> Path:
    try:
        path = Path(value).expanduser().absolute()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_workspace_invalid") from exc
    if (
        "\x00" in path.as_posix()
        or ".." in path.parts
        or len(path.parts) > 128
        or len(path.as_posix().encode("utf-8")) > 4096
        or path.is_symlink()
        or not path.is_dir()
    ):
        _fail("producer_bundle_preflight_workspace_invalid")
    return path


def _regular_directory(path: Path, code: str) -> None:
    if path.is_symlink() or not path.exists() or not path.is_dir():
        _fail(code)


def _batch_path(workspace: Path, journal_id: str) -> Path:
    if not isinstance(journal_id, str) or _IDENTIFIER.fullmatch(journal_id) is None:
        _fail("producer_bundle_preflight_journal_id_invalid")
    evolution = workspace / "evolution"
    batches = evolution / "producer-batches"
    batch = batches / journal_id
    # Check each derived component without resolving symlinks.  A caller cannot redirect a
    # journal to a sibling or outside the run workspace by supplying a link.
    _regular_directory(evolution, "producer_bundle_preflight_evolution_missing")
    _regular_directory(batches, "producer_bundle_preflight_batches_missing")
    _regular_directory(batch, "producer_bundle_preflight_batch_missing")
    return batch


def _read_digest(path: Path, maximum: int, missing_digest: str) -> str:
    if path.is_symlink():
        _fail("producer_bundle_preflight_archive_path_invalid")
    if not path.exists():
        return missing_digest
    try:
        content = _files.read_regular_file(path, maximum)
    except _files.BenchmarkFileError as exc:
        _fail({"missing": "producer_bundle_preflight_archive_missing",
               "too_large": "producer_bundle_preflight_archive_too_large",
               "unsafe": "producer_bundle_preflight_archive_path_invalid",
               "changed": "producer_bundle_preflight_archive_changed"}.get(
                   exc.reason, "producer_bundle_preflight_archive_invalid"))
    return hashlib.sha256(content).hexdigest()


def compute_archive_prefix_digest(
    archive_sha256: str,
    state_sha256: str,
    *,
    seed_commit_sha256: str | None = None,
    strategy_config_sha256: str | None = None,
    active_ids_sha256: str | None = None,
) -> str:
    """Compute the canonical digest of an existing archive/state prefix.

    ``archive_sha256`` and ``state_sha256`` are digests of the exact native bytes.  The optional
    seed marker is included when present so a prefix cannot silently omit recovery evidence.
    """
    archive_sha256 = _digest(archive_sha256, "producer_bundle_preflight_archive_digest_invalid")
    state_sha256 = _digest(state_sha256, "producer_bundle_preflight_state_digest_invalid")
    if seed_commit_sha256 is not None:
        seed_commit_sha256 = _digest(
            seed_commit_sha256, "producer_bundle_preflight_seed_commit_digest_invalid",
        )
    if strategy_config_sha256 is not None:
        strategy_config_sha256 = _digest(
            strategy_config_sha256, "producer_bundle_preflight_strategy_config_digest_invalid",
        )
    if active_ids_sha256 is not None:
        active_ids_sha256 = _digest(
            active_ids_sha256, "producer_bundle_preflight_active_ids_digest_invalid",
        )
    payload: dict[str, str] = {
        "archive_sha256": archive_sha256,
        "state_sha256": state_sha256,
    }
    if seed_commit_sha256 is not None:
        payload["seed_commit_sha256"] = seed_commit_sha256
    if strategy_config_sha256 is not None:
        payload["strategy_config_sha256"] = strategy_config_sha256
    if active_ids_sha256 is not None:
        payload["active_ids_sha256"] = active_ids_sha256
    return hashlib.sha256(_canonical(payload)).hexdigest()


def derive_producer_bundle_candidate_id(
    journal_id: str,
    ordinal: int,
    bundle_id: str,
    bundle_sha256: str,
) -> str:
    """Derive the fixed candidate identity for one plan-order bundle."""
    if not isinstance(journal_id, str) or _IDENTIFIER.fullmatch(journal_id) is None:
        _fail("producer_bundle_preflight_journal_id_invalid")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 0 <= ordinal <= 31:
        _fail("producer_bundle_preflight_candidate_ordinal_invalid")
    if not isinstance(bundle_id, str) or _IDENTIFIER.fullmatch(bundle_id) is None:
        _fail("producer_bundle_preflight_bundle_id_invalid")
    bundle_sha256 = _digest(bundle_sha256, "producer_bundle_preflight_bundle_digest_invalid")
    payload = {
        "journal_id": journal_id, "ordinal": ordinal,
        "bundle_id": bundle_id, "bundle_sha256": bundle_sha256,
    }
    return "candidate-" + hashlib.sha256(_canonical(payload)).hexdigest()[:32]


_RECEIPT_FIELDS = {
    "schema_version", "protocol", "journal_id", "run_id", "task_id", "plan_sha256",
    "archive_prefix_sha256", "base_archive_sha256", "base_state_sha256", "authority_sha256",
    "candidate_ids", "record_count", "workspace_relative", "receipt_sha256",
}


@dataclass(frozen=True, slots=True)
class ProducerBundlePreflightReceipt:
    """Bounded evidence that a publication batch passed read-only preflight."""

    journal_id: str
    run_id: str
    task_id: str
    plan_sha256: str
    archive_prefix_sha256: str
    base_archive_sha256: str
    base_state_sha256: str
    authority_sha256: str
    candidate_ids: tuple[str, ...]
    record_count: int
    workspace_relative: str
    schema_version: str = _SCHEMA_VERSION
    protocol: str = _PROTOCOL
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION or self.protocol != _PROTOCOL:
            _fail("producer_bundle_preflight_schema_invalid")
        for name, value in (
            ("journal_id", self.journal_id), ("run_id", self.run_id), ("task_id", self.task_id),
        ):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                _fail("producer_bundle_preflight_identifier_invalid")
        for name, value in (
            ("plan_sha256", self.plan_sha256), ("archive_prefix_sha256", self.archive_prefix_sha256),
            ("base_archive_sha256", self.base_archive_sha256), ("base_state_sha256", self.base_state_sha256),
            ("authority_sha256", self.authority_sha256),
        ):
            _digest(value, f"producer_bundle_preflight_{name}_invalid")
        if (
            not isinstance(self.candidate_ids, tuple)
            or not self.candidate_ids
            or len(self.candidate_ids) > 32
            or any(not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in self.candidate_ids)
            or len(set(self.candidate_ids)) != len(self.candidate_ids)
        ):
            _fail("producer_bundle_preflight_candidates_invalid")
        if isinstance(self.record_count, bool) or not isinstance(self.record_count, int) or not 0 <= self.record_count <= 10000:
            _fail("producer_bundle_preflight_record_count_invalid")
        if (
            not isinstance(self.workspace_relative, str)
            or self.workspace_relative != "evolution/producer-batches/" + self.journal_id
        ):
            _fail("producer_bundle_preflight_workspace_invalid")
        expected = hashlib.sha256(_canonical(self._payload_dict())).hexdigest()
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_bundle_preflight_receipt_digest_mismatch")
        _canonical(self.to_dict())

    def _payload_dict(self) -> dict[str, object]:
        payload = self.to_dict()
        payload.pop("receipt_sha256", None)
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "journal_id": self.journal_id, "run_id": self.run_id, "task_id": self.task_id,
            "plan_sha256": self.plan_sha256, "archive_prefix_sha256": self.archive_prefix_sha256,
            "base_archive_sha256": self.base_archive_sha256, "base_state_sha256": self.base_state_sha256,
            "authority_sha256": self.authority_sha256, "candidate_ids": list(self.candidate_ids),
            "record_count": self.record_count, "workspace_relative": self.workspace_relative,
            "receipt_sha256": self.receipt_sha256,
        }

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self._payload_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundlePreflightReceipt:
        raw = _object(value, _RECEIPT_FIELDS)
        if not isinstance(raw["candidate_ids"], list):
            _fail("producer_bundle_preflight_candidates_invalid")
        if raw.get("receipt_sha256") is None:
            _fail("producer_bundle_preflight_receipt_digest_mismatch")
        return cls(**{**raw, "candidate_ids": tuple(raw["candidate_ids"])})  # type: ignore[arg-type]


def parse_producer_bundle_preflight_receipt(
    source: Mapping[str, object] | str | os.PathLike[str],
) -> ProducerBundlePreflightReceipt:
    try:
        if isinstance(source, Mapping):
            raw = strict_json(_canonical(dict(source)), MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES)
        else:
            content = _files.read_regular_file(
                _files.absolute_path(source), MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES,
            )
            raw = strict_json(content, MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES)
        return ProducerBundlePreflightReceipt.from_dict(raw)
    except ProducerBundlePreflightError:
        raise
    except Exception as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_receipt_invalid") from exc


def _authority_digest(journal: ProducerBundlePublicationJournal) -> str:
    return hashlib.sha256(_canonical({
        "contract_sha256": journal.contract_sha256,
        "evaluator_kind": journal.evaluator_kind,
        "evaluator_fingerprint": journal.evaluator_fingerprint,
        "runner_fingerprint": journal.runner_fingerprint,
        "dependency_sha256": journal.dependency_sha256,
        "environment_sha256": journal.environment_sha256,
        "budget_sha256": journal.budget_sha256,
    })).hexdigest()


def preflight_producer_bundle_publication(
    workspace: str | Path,
    plan: ProducerBundleAdmissionPlan,
    journal: ProducerBundlePublicationJournal,
    *,
    budget_sha256: str | None = None,
) -> ProducerBundlePreflightReceipt:
    """Validate a producer publication intent against an existing archive with zero writes."""
    if not isinstance(plan, ProducerBundleAdmissionPlan):
        _fail("producer_bundle_preflight_plan_invalid")
    if not isinstance(journal, ProducerBundlePublicationJournal):
        _fail("producer_bundle_preflight_journal_invalid")
    if journal.strategy != "population":
        _fail("producer_bundle_preflight_strategy_unsupported")
    if journal.state != "prepared" or journal.publication_phase != "preflight":
        _fail("producer_bundle_preflight_journal_state_invalid")
    try:
        plan_digest = plan.digest()
    except Exception as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_plan_invalid") from exc
    if journal.admission_sha256 != plan_digest:
        _fail("producer_bundle_preflight_plan_digest_mismatch")
    authority = {
        "contract_sha256": plan.contract_sha256,
        "evaluator_kind": plan.evaluator_kind,
        "evaluator_fingerprint": plan.evaluator_fingerprint,
        "runner_fingerprint": plan.runner_fingerprint,
        "dependency_sha256": plan.dependency_sha256,
        "environment_sha256": plan.environment_sha256,
    }
    if any(getattr(journal, key) != value for key, value in authority.items()):
        _fail("producer_bundle_preflight_authority_mismatch")
    if budget_sha256 is not None:
        _digest(budget_sha256, "producer_bundle_preflight_budget_invalid")
        if journal.budget_sha256 != budget_sha256:
            _fail("producer_bundle_preflight_budget_mismatch")
    if len(journal.candidates) != len(plan.bundles):
        _fail("producer_bundle_preflight_plan_candidates_mismatch")
    for ordinal, (candidate, bundle) in enumerate(zip(journal.candidates, plan.bundles, strict=True)):
        if candidate.bundle_id != bundle.bundle_id or candidate.bundle_sha256 != bundle.bundle_sha256:
            _fail("producer_bundle_preflight_plan_candidates_mismatch")
        if candidate.candidate_id != derive_producer_bundle_candidate_id(
            journal.journal_id, ordinal, bundle.bundle_id, bundle.bundle_sha256,
        ):
            _fail("producer_bundle_preflight_candidate_id_mismatch")
    workspace_path = _safe_workspace(workspace)
    _batch_path(workspace_path, journal.journal_id)

    # CandidateArchive(read_only=True) performs no mkdir/recovery and then validates native
    # records/receipts through its public integrity API.  Legacy seed handoff records remain a
    # separate protocol and are explicitly rejected by this transaction boundary.
    try:
        archive = CandidateArchive(workspace_path, requested_strategy="population", read_only=True)
        records = tuple(archive.records())
        state = archive.read_state()
        if any(
            candidate.strategy != "population"
            or "seed_handoff" in candidate.metadata
            or candidate.candidate_id.startswith("seed-")
            for candidate in records
        ):
            _fail("producer_bundle_preflight_seed_records_unsupported")
        archive.validate_candidate_integrity(require_all=True, records=records)
    except ProducerBundlePreflightError:
        raise
    except EvolutionError as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_archive_integrity_invalid") from exc
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ProducerBundlePreflightError("producer_bundle_preflight_archive_integrity_invalid") from exc

    # If a native authority projection exists, compare every pin before publication.  This catches
    # a journal copied to a workspace belonging to another evaluator or contract.
    projected = state.get("candidate_integrity_authority") if isinstance(state, dict) else None
    if projected is not None:
        try:
            native = CandidateIntegrityAuthority.from_dict(projected)
        except (EvolutionError, TypeError, ValueError) as exc:
            raise ProducerBundlePreflightError("producer_bundle_preflight_authority_invalid") from exc
        if any(getattr(native, key) != value for key, value in authority.items() if key != "evaluator_kind"):
            _fail("producer_bundle_preflight_authority_mismatch")
        if native.evaluator_kind != plan.evaluator_kind:
            _fail("producer_bundle_preflight_authority_mismatch")

    archive_file = workspace_path / "evolution" / "archive.jsonl"
    state_file = workspace_path / "evolution" / "state.json"
    archive_sha = _read_digest(archive_file, MAX_ARCHIVE_BYTES, hashlib.sha256(b"").hexdigest())
    state_sha = _read_digest(state_file, MAX_STATE_BYTES, hashlib.sha256(b"").hexdigest())
    if archive_sha != journal.base_archive_sha256:
        _fail("producer_bundle_preflight_archive_prefix_mismatch")
    if state_sha != journal.base_state_sha256:
        _fail("producer_bundle_preflight_state_prefix_mismatch")
    config = state.get("config") if isinstance(state, dict) else None
    config_sha = hashlib.sha256(_canonical(config)).hexdigest() if config is not None else None
    active_ids = state.get("active_ids") if isinstance(state, dict) else None
    active_ids_sha = hashlib.sha256(_canonical(active_ids)).hexdigest() if active_ids is not None else None
    seed_commit = workspace_path / "evolution" / "seed-commit.json"
    if seed_commit.is_symlink():
        _fail("producer_bundle_preflight_archive_path_invalid")
    seed_commit_sha = (
        _read_digest(seed_commit, MAX_ARCHIVE_BYTES, hashlib.sha256(b"").hexdigest())
        if seed_commit.exists() else None
    )
    if config is None or active_ids is None:
        _fail("producer_bundle_preflight_population_config_missing")
    if state.get("strategy") != journal.strategy:
        _fail("producer_bundle_preflight_population_config_mismatch")
    prefix = compute_archive_prefix_digest(
        archive_sha,
        state_sha,
        seed_commit_sha256=seed_commit_sha,
        strategy_config_sha256=config_sha,
        active_ids_sha256=active_ids_sha,
    )
    if prefix != journal.archive_prefix_sha256:
        _fail("producer_bundle_preflight_archive_prefix_mismatch")
    if config is not None:
        assert config_sha is not None
        if config_sha != journal.population_config_sha256:
            _fail("producer_bundle_preflight_population_config_mismatch")
        if config.get("num_islands") != journal.num_islands:
            _fail("producer_bundle_preflight_population_config_mismatch")
    candidate_ids = tuple(item.candidate_id for item in journal.candidates)
    if set(candidate_ids) & {item.candidate_id for item in records}:
        _fail("producer_bundle_preflight_candidate_id_collision")
    return ProducerBundlePreflightReceipt(
        journal_id=journal.journal_id,
        run_id=journal.run_id,
        task_id=journal.task_id,
        plan_sha256=plan_digest,
        archive_prefix_sha256=prefix,
        base_archive_sha256=archive_sha,
        base_state_sha256=state_sha,
        authority_sha256=_authority_digest(journal),
        candidate_ids=candidate_ids,
        record_count=len(records),
        workspace_relative=f"evolution/producer-batches/{journal.journal_id}",
    )


__all__ = [
    "MAX_PRODUCER_BUNDLE_PREFLIGHT_BYTES",
    "ProducerBundlePreflightError",
    "ProducerBundlePreflightReceipt",
    "compute_archive_prefix_digest",
    "derive_producer_bundle_candidate_id",
    "parse_producer_bundle_preflight_receipt",
    "preflight_producer_bundle_publication",
]
