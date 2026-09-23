"""Project verified producer bundles into native multi-file candidate drafts.

The producer bundle bridge intentionally stops before execution and evaluation.  This module is
the next, still provider-free boundary: it re-reads the verified source files, binds their bytes
to the existing ``CandidateDraft(source_files=...)`` shape, and carries producer provenance as
metadata.  Callers can pass the resulting drafts to the native ``MultiFileCandidatePipeline``.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files as _files
from .candidate_bundle import CandidateBundleError, verify_candidate_source_bundle
from .evolution import CandidateDraft
from .producer_bundle_handoff import VerifiedProducerBundle

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ProducerBundlePopulationError(ValueError):
    """Fixed-code failure while projecting a verified bundle into a native draft."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundlePopulationError(code)


@dataclass(frozen=True, slots=True)
class ProducerBundleDraft:
    """A native multi-file draft plus producer provenance kept outside candidate identity."""

    bundle_id: str
    draft: CandidateDraft
    bundle_sha256: str
    producer_fingerprint: str
    producer_id: str | None = None
    envelope_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_id, str) or _IDENTIFIER.fullmatch(self.bundle_id) is None:
            _fail("producer_bundle_population_id_invalid")
        if not isinstance(self.draft, CandidateDraft) or self.draft.source_files is None:
            _fail("producer_bundle_population_draft_invalid")
        if not isinstance(self.bundle_sha256, str) or _SHA256.fullmatch(self.bundle_sha256) is None:
            _fail("producer_bundle_population_digest_invalid")
        if (
            not isinstance(self.producer_fingerprint, str)
            or _SHA256.fullmatch(self.producer_fingerprint) is None
        ):
            _fail("producer_bundle_population_identity_invalid")
        if self.producer_id is not None and (
            not isinstance(self.producer_id, str)
            or _IDENTIFIER.fullmatch(self.producer_id) is None
        ):
            _fail("producer_bundle_population_producer_id_invalid")
        if self.envelope_sha256 is not None and (
            not isinstance(self.envelope_sha256, str)
            or _SHA256.fullmatch(self.envelope_sha256) is None
        ):
            _fail("producer_bundle_population_envelope_sha256_invalid")

    @property
    def entrypoint(self) -> str:
        return self.draft.filename

    @property
    def material_paths(self) -> tuple[str, ...]:
        return tuple(self.draft.source_files or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "bundle_sha256": self.bundle_sha256,
            "producer_fingerprint": self.producer_fingerprint,
            "producer_id": self.producer_id,
            "envelope_sha256": self.envelope_sha256,
            "entrypoint": self.entrypoint,
            "material_paths": list(self.material_paths),
            "metadata": dict(self.draft.metadata),
        }


def _read_source(path: Path, size: int, expected_sha256: str) -> bytes:
    try:
        content = _files.read_regular_file(
            _files.absolute_path(path), size, exact_size=True,
        )
    except _files.BenchmarkFileError as exc:
        code = "producer_bundle_population_source_missing" if exc.reason == "missing" else (
            "producer_bundle_population_source_unsafe"
            if exc.reason == "unsafe" else "producer_bundle_population_source_changed"
        )
        _fail(code)
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        _fail("producer_bundle_population_source_changed")
    return content


def _read_sources(bundle: VerifiedProducerBundle, root: Path) -> dict[str, str]:
    try:
        verified = verify_candidate_source_bundle(
            bundle.bundle,
            source_root=root,
            contract_sha256=bundle.contract_sha256,
            expected_bundle_sha256=bundle.bundle_sha256,
        )
        values: dict[str, str] = {}
        for item in verified.bundle.files:
            content = _read_source(root / item.path, item.size, item.sha256)
            try:
                values[item.path] = content.decode("utf-8")
            except UnicodeDecodeError:
                _fail("producer_bundle_population_source_encoding_invalid")
        return values
    except ProducerBundlePopulationError:
        raise
    except CandidateBundleError as exc:
        if exc.code.startswith("candidate_bundle_source_"):
            suffix = exc.code.removeprefix("candidate_bundle_")
            raise ProducerBundlePopulationError(
                f"producer_bundle_population_{suffix}"
            ) from exc
        raise ProducerBundlePopulationError("producer_bundle_population_source_invalid") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise ProducerBundlePopulationError("producer_bundle_population_source_invalid") from exc


def prepare_producer_bundle_drafts(
    external_root: str | os.PathLike[str],
    bundles: tuple[VerifiedProducerBundle, ...] | list[VerifiedProducerBundle],
) -> tuple[ProducerBundleDraft, ...]:
    """Read verified producer bundles into native multi-file ``CandidateDraft`` values.

    The input ordering is preserved for caller-controlled scheduling.  Bundle IDs and source
    paths must remain unique in one call, and every source is reverified before it is decoded.
    No files are copied or written, and producer evidence is never used as a local score.
    """

    if isinstance(bundles, (str, bytes)) or not isinstance(bundles, (tuple, list)) or not bundles:
        _fail("producer_bundle_population_bundles_invalid")
    try:
        root = _files.absolute_path(external_root)
        root_info = root.lstat()
    except (OSError, TypeError, ValueError) as exc:
        raise ProducerBundlePopulationError("producer_bundle_population_root_invalid") from exc
    if not root_info or not root.is_dir() or root.is_symlink():
        _fail("producer_bundle_population_root_invalid")

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    result: list[ProducerBundleDraft] = []
    for bundle in bundles:
        if not isinstance(bundle, VerifiedProducerBundle):
            _fail("producer_bundle_population_bundle_invalid")
        if bundle.bundle_id in seen_ids:
            _fail("producer_bundle_population_id_duplicate")
        seen_ids.add(bundle.bundle_id)
        paths = tuple(item.path for item in bundle.bundle.files)
        if seen_paths.intersection(paths):
            _fail("producer_bundle_population_path_reused")
        seen_paths.update(paths)
        sources = _read_sources(bundle, root)
        metadata = {
            "producer_bundle": {
                "bundle_id": bundle.bundle_id,
                "bundle_sha256": bundle.bundle_sha256,
                "producer_fingerprint": bundle.producer_fingerprint,
                "producer_id": bundle.producer_id,
                "envelope_sha256": bundle.envelope_sha256,
            }
        }
        try:
            draft = CandidateDraft.from_files(sources, bundle.entrypoint, metadata)
        except Exception as exc:
            raise ProducerBundlePopulationError("producer_bundle_population_draft_invalid") from exc
        result.append(
            ProducerBundleDraft(
                bundle_id=bundle.bundle_id,
                draft=draft,
                bundle_sha256=bundle.bundle_sha256,
                producer_fingerprint=bundle.producer_fingerprint,
                producer_id=bundle.producer_id,
                envelope_sha256=bundle.envelope_sha256,
            )
        )
    return tuple(result)


__all__ = ["ProducerBundleDraft", "ProducerBundlePopulationError", "prepare_producer_bundle_drafts"]
