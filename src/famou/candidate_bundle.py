"""Bounded, read-only manifests for collections of candidate source files.

This boundary binds only the declared UTF-8 source bytes. It neither imports those sources nor
admits them as an executable candidate, seed, repository, or workflow. Source checks use stable
file descriptors for each read; they do not create an atomic snapshot across multiple files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files

CANDIDATE_BUNDLE_PROTOCOL = "lunar-candidate-source-bundle-v1"
CANDIDATE_BUNDLE_SCHEMA_VERSION = "1"
MAX_CANDIDATE_BUNDLE_BYTES = 128 * 1024
MAX_CANDIDATE_BUNDLE_FILES = 64
MAX_CANDIDATE_SOURCE_BYTES = 1024 * 1024
MAX_CANDIDATE_TOTAL_SOURCE_BYTES = 16 * 1024 * 1024
MAX_CANDIDATE_PATH_BYTES = 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CandidateBundleError(ValueError):
    """A fixed-code manifest or source verification failure without source prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(suffix: str) -> None:
    raise CandidateBundleError("candidate_bundle_" + suffix)


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("invalid")
    return value


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_CANDIDATE_PATH_BYTES:
        _fail("path_unsafe")
    if (
        "\\" in value or ":" in value
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
        or unicodedata.normalize("NFC", value) != value
    ):
        _fail("path_unsafe")
    try:
        if len(value.encode("utf-8")) > MAX_CANDIDATE_PATH_BYTES:
            _fail("path_unsafe")
    except UnicodeEncodeError:
        _fail("path_unsafe")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts):
        _fail("path_unsafe")
    return value


def _strict_object(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail("invalid")
    if set(value) != fields:
        _fail("invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        content = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("invalid")
    if len(content) > MAX_CANDIDATE_BUNDLE_BYTES:
        _fail("too_large")
    return content


def _strict_loads(content: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("invalid")
            result[key] = value
        return result

    def constant(_value: str) -> object:
        _fail("invalid")

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except CandidateBundleError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        _fail("invalid")


@dataclass(frozen=True)
class CandidateSourceFile:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _relative_path(self.path)
        if (
            isinstance(self.size, bool) or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_CANDIDATE_SOURCE_BYTES
        ):
            _fail("invalid")
        _digest(self.sha256)

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: object) -> CandidateSourceFile:
        item = _strict_object(value, {"path", "size", "sha256"})
        return cls(item["path"], item["size"], item["sha256"])


def _check_path_collisions(files: tuple[CandidateSourceFile, ...]) -> None:
    # Keep directory spellings too: lib/a.py and LIB/b.py alias on common filesystems.
    nodes: dict[str, tuple[str, bool]] = {}
    for source in files:
        parts = source.path.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            folded = unicodedata.normalize("NFC", prefix.casefold())
            is_file = depth == len(parts)
            if folded in nodes:
                existing, existing_is_file = nodes[folded]
                if prefix != existing or is_file or existing_is_file:
                    _fail("path_unsafe")
            nodes[folded] = (prefix, is_file)


@dataclass(frozen=True)
class CandidateSourceBundle:
    contract_sha256: str
    entrypoint: str
    files: tuple[CandidateSourceFile, ...]
    schema_version: str = CANDIDATE_BUNDLE_SCHEMA_VERSION
    protocol: str = CANDIDATE_BUNDLE_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_BUNDLE_SCHEMA_VERSION or self.protocol != CANDIDATE_BUNDLE_PROTOCOL:
            _fail("invalid")
        _digest(self.contract_sha256)
        _relative_path(self.entrypoint)
        if not isinstance(self.files, (tuple, list)) or not 1 <= len(self.files) <= MAX_CANDIDATE_BUNDLE_FILES:
            _fail("invalid")
        normalized: list[CandidateSourceFile] = []
        for source in self.files:
            if not isinstance(source, CandidateSourceFile):
                _fail("invalid")
            # Detach the manifest from mutable caller containers or later DTO tampering.
            normalized.append(CandidateSourceFile(source.path, source.size, source.sha256))
        files = tuple(sorted(normalized, key=lambda item: item.path))
        if sum(source.size for source in files) > MAX_CANDIDATE_TOTAL_SOURCE_BYTES:
            _fail("invalid")
        _check_path_collisions(files)
        if self.entrypoint not in {source.path for source in files}:
            _fail("invalid")
        object.__setattr__(self, "files", files)
        _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "contract_sha256": self.contract_sha256,
            "entrypoint": self.entrypoint,
            "files": [source.to_dict() for source in self.files],
        }

    def digest(self) -> str:
        """Hash the whole canonical manifest, independently of source-list input order."""
        validated = validate_candidate_source_bundle(self)
        return hashlib.sha256(_canonical_bytes(validated.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> CandidateSourceBundle:
        item = _strict_object(
            value, {"schema_version", "protocol", "contract_sha256", "entrypoint", "files"},
        )
        raw_files = item["files"]
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_CANDIDATE_BUNDLE_FILES:
            _fail("invalid")
        return cls(
            item["contract_sha256"], item["entrypoint"],
            tuple(CandidateSourceFile.from_dict(source) for source in raw_files),
            item["schema_version"], item["protocol"],
        )


def parse_candidate_source_bundle(
    source: str | os.PathLike[str] | Mapping[str, object],
) -> CandidateSourceBundle:
    """Parse a strict bounded manifest without reading or executing candidate sources."""
    try:
        if isinstance(source, Mapping):
            return CandidateSourceBundle.from_dict(dict(source))
        try:
            content = _files.read_regular_file(
                _files.absolute_path(source), MAX_CANDIDATE_BUNDLE_BYTES,
            )
        except _files.BenchmarkFileError as exc:
            _fail("too_large" if exc.reason == "too_large" else "invalid")
        return CandidateSourceBundle.from_dict(_strict_loads(content))
    except CandidateBundleError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


def validate_candidate_source_bundle(bundle: CandidateSourceBundle) -> CandidateSourceBundle:
    """Rebuild and validate a DTO, including nested values changed since construction."""
    try:
        if not isinstance(bundle, CandidateSourceBundle):
            _fail("invalid")
        return CandidateSourceBundle.from_dict(bundle.to_dict())
    except CandidateBundleError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


@dataclass(frozen=True)
class VerifiedCandidateSourceBundle:
    bundle: CandidateSourceBundle
    bundle_sha256: str
    file_count: int
    total_bytes: int


def _verify_source(root: Path, source: CandidateSourceFile) -> None:
    try:
        content = _files.read_regular_file(
            _files.absolute_path(root / source.path), source.size, exact_size=True,
        )
    except _files.BenchmarkFileError as exc:
        suffix = {"unsafe": "unsafe", "missing": "missing"}.get(exc.reason, "changed")
        _fail("source_" + suffix)
    if len(content) != source.size or hashlib.sha256(content).hexdigest() != source.sha256:
        _fail("source_changed")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        _fail("source_encoding_invalid")
    if b"\x00" in content:
        _fail("source_encoding_invalid")


def verify_candidate_source_bundle(
    bundle: CandidateSourceBundle | Mapping[str, object] | str | os.PathLike[str],
    *,
    source_root: str | os.PathLike[str],
    contract_sha256: str,
    expected_bundle_sha256: str | None = None,
) -> VerifiedCandidateSourceBundle:
    """Verify caller pins and declared local bytes, without copying, admitting, or executing.

    Each source has its own bounded read and descriptor/name checks. Undeclared files are ignored,
    and success does not claim the source collection existed as one atomic filesystem snapshot.
    """
    parsed = (
        validate_candidate_source_bundle(bundle)
        if isinstance(bundle, CandidateSourceBundle)
        else parse_candidate_source_bundle(bundle)
    )
    expected_contract = _digest(contract_sha256)
    expected_identity = None if expected_bundle_sha256 is None else _digest(expected_bundle_sha256)
    if parsed.contract_sha256 != expected_contract:
        _fail("contract_mismatch")
    identity = parsed.digest()
    if expected_identity is not None and expected_identity != identity:
        _fail("identity_mismatch")
    try:
        root = _files.absolute_path(source_root)
        if not stat.S_ISDIR(root.lstat().st_mode):
            _fail("root_unsafe")
    except (OSError, _files.BenchmarkFileError):
        _fail("root_unsafe")
    for source in parsed.files:
        _verify_source(root, source)
    return VerifiedCandidateSourceBundle(
        parsed, identity, len(parsed.files), sum(source.size for source in parsed.files),
    )


__all__ = [
    "CANDIDATE_BUNDLE_PROTOCOL",
    "CANDIDATE_BUNDLE_SCHEMA_VERSION",
    "MAX_CANDIDATE_BUNDLE_BYTES",
    "MAX_CANDIDATE_BUNDLE_FILES",
    "MAX_CANDIDATE_PATH_BYTES",
    "MAX_CANDIDATE_SOURCE_BYTES",
    "MAX_CANDIDATE_TOTAL_SOURCE_BYTES",
    "CandidateBundleError",
    "CandidateSourceBundle",
    "CandidateSourceFile",
    "VerifiedCandidateSourceBundle",
    "parse_candidate_source_bundle",
    "validate_candidate_source_bundle",
    "verify_candidate_source_bundle",
]
