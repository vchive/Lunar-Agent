"""Portable delivery copies of selected bundles and their already scored outputs."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files
from ._candidate_workspace_io import DirectoryChain, PrivateTree
from .algorithm import MAX_OUTPUTS
from .candidate_bundle import (
    MAX_CANDIDATE_BUNDLE_FILES,
    MAX_CANDIDATE_PATH_BYTES,
    CandidateSourceFile,
    _check_path_collisions,
)
from .candidate_evaluation_spec import canonical_json, strict_json
from .candidate_execution import MAX_EXECUTION_INPUTS
from .candidate_workspace_plan import CandidateWorkspaceError
from .evolution import EvolutionError

_PROTOCOL = "lunar-bundle-delivery-v1"
_MANIFEST = "delivery.json"
_MAX_FILES = MAX_CANDIDATE_BUNDLE_FILES + MAX_EXECUTION_INPUTS + MAX_OUTPUTS + 5
# Paths may need JSON escaping, and source paths gain the seven-byte delivery prefix. The
# remaining allowance covers descriptors and fixed identity fields even at all three file caps.
_MAX_MANIFEST_BYTES = 4096 + _MAX_FILES * (2 * (MAX_CANDIDATE_PATH_BYTES + 7) + 128)
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 99 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_FIELDS = {
    "candidate_id", "contract_sha256", "bundle_sha256", "receipt_sha256",
    "evaluation_sha256",
}


@dataclass(frozen=True)
class _DeliveryPath:
    path: str


def _fail() -> None:
    raise EvolutionError("bundle_delivery_invalid")


def _close_tree(tree: PrivateTree) -> None:
    active = sys.exception()
    try:
        tree.close()
    except BaseException:  # Preserve an active interruption even if releasing the tree fails.
        if not isinstance(active, (KeyboardInterrupt, SystemExit)):
            raise


def _identity(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _IDENTITY_FIELDS:
        _fail()
    if not isinstance(value["candidate_id"], str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["candidate_id"],
    ) is None:
        _fail()
    if any(not isinstance(value[key], str) or _SHA.fullmatch(value[key]) is None
           for key in _IDENTITY_FIELDS - {"candidate_id"}):
        _fail()
    return dict(value)


def _paths(paths: list[str]) -> None:
    # The bundle validator also rejects parent/file collisions and case aliases. Its per-source
    # size limit is irrelevant here: zero-byte declarations are used only for path validation.
    try:
        if not 3 <= len(paths) <= _MAX_FILES:
            _fail()
        for path in paths:
            if not isinstance(path, str):
                _fail()
            # The delivery adds a namespace to source paths; retain the full original 1 KiB
            # source-path allowance rather than charging that prefix against its limit.
            CandidateSourceFile(path.removeprefix("source/").removeprefix("inputs/"), 0, "0" * 64)
        _check_path_collisions(tuple(_DeliveryPath(path) for path in paths))
        if "source-bundle.json" not in paths or "evaluation/report.json" not in paths:
            _fail()
        if not any(path.startswith("source/") for path in paths):
            _fail()
        if any(path not in {
            "source-bundle.json", "evaluation/report.json", "evaluation/evaluator.py",
            "evaluation/spec.json", "contract.json",
        } and not path.startswith(("source/", "output/", "inputs/")) for path in paths):
            _fail()
    except (TypeError, ValueError):
        _fail()


@dataclass(frozen=True)
class BundleDeliveryResult:
    delivery_path: Path
    _manifest: bytes

    def digest(self) -> str:
        return hashlib.sha256(self._manifest).hexdigest()

    def to_dict(self) -> dict:
        manifest = strict_json(self._manifest, maximum=_MAX_MANIFEST_BYTES)
        return {"status": "delivered", "delivery_sha256": self.digest(), **manifest}


def _inventory(path: Path, chain: DirectoryChain, expected: set[str]) -> None:
    directories = {""}
    for relative in expected:
        directories.update(parent.as_posix() for parent in Path(relative).parents if str(parent) != ".")
    seen: set[str] = set()
    for directory in sorted(directories):
        root = path / directory
        held = DirectoryChain(root, "bundle_delivery_invalid")
        try:
            for name in os.listdir(held.fd):
                relative = f"{directory}/{name}" if directory else name
                if relative not in expected and relative not in directories:
                    _fail()
                seen.add(relative)
            held.check()
        finally:
            held.close()
    if seen != expected | (directories - {""}):
        _fail()
    chain.check()


def inspect_bundle_delivery(delivery_path, *, expected_delivery_sha256=None) -> BundleDeliveryResult:
    """Read a portable delivery and verify all declared bytes without running any code."""
    if expected_delivery_sha256 is not None and (
        not isinstance(expected_delivery_sha256, str)
        or _SHA.fullmatch(expected_delivery_sha256) is None
    ):
        _fail()
    try:
        path = _benchmark_files.absolute_path(delivery_path)
        chain = DirectoryChain(path, "bundle_delivery_invalid")
        try:
            raw = _benchmark_files.read_regular_file(path / _MANIFEST, _MAX_MANIFEST_BYTES)
            manifest = strict_json(raw, maximum=_MAX_MANIFEST_BYTES)
            if not isinstance(manifest, dict) or set(manifest) != {
                "schema_version", "protocol", "observation", "identity", "files",
            }:
                _fail()
            if (manifest["schema_version"] != "1" or manifest["protocol"] != _PROTOCOL
                    or manifest["observation"] != "evaluation-time"
                    or canonical_json(manifest, maximum=_MAX_MANIFEST_BYTES) != raw):
                _fail()
            _identity(manifest["identity"])
            if expected_delivery_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_delivery_sha256:
                _fail()
            files = manifest["files"]
            if not isinstance(files, dict):
                _fail()
            _paths(list(files))
            total = 0
            for relative, descriptor in files.items():
                if not isinstance(descriptor, dict) or set(descriptor) != {"size", "sha256"}:
                    _fail()
                size = descriptor["size"]
                if type(size) is not int or not 0 <= size <= _MAX_FILE_BYTES:
                    _fail()
                total += size
                if total > _MAX_TOTAL_BYTES:
                    _fail()
                content = _benchmark_files.read_regular_file(path / relative, size, exact_size=True)
                if hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
                    _fail()
            _inventory(path, chain, {*files, _MANIFEST})
            if _benchmark_files.read_regular_file(path / _MANIFEST, _MAX_MANIFEST_BYTES) != raw:
                _fail()
            chain.check()
            return BundleDeliveryResult(path, raw)
        finally:
            chain.close()
    except (_benchmark_files.BenchmarkFileError, CandidateWorkspaceError, OSError, TypeError, ValueError):
        _fail()


def bundle_delivery_manifest(*, identity: dict, materials: dict[str, bytes]) -> bytes:
    """Validate portable materials and encode their manifest without allocating a copy."""
    identity = _identity(identity)
    if not isinstance(materials, dict):
        _fail()
    _paths(list(materials))
    if any(not isinstance(content, bytes) or len(content) > _MAX_FILE_BYTES for content in materials.values()):
        _fail()
    if sum(map(len, materials.values())) > _MAX_TOTAL_BYTES:
        _fail()
    return canonical_json({
        "schema_version": "1", "protocol": _PROTOCOL, "observation": "evaluation-time",
        "identity": identity, "files": {
            path: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for path, content in sorted(materials.items())
        },
    }, maximum=_MAX_MANIFEST_BYTES)


def publish_bundle_delivery(destination_root, *, identity: dict, materials: dict[str, bytes]) -> BundleDeliveryResult:
    """Write one new private delivery directory; never overwrite or repair an earlier copy."""
    raw = bundle_delivery_manifest(identity=identity, materials=materials)
    try:
        root = _benchmark_files.absolute_path(destination_root)
        chain = DirectoryChain(root, "bundle_delivery_invalid")
        try:
            tree = PrivateTree(chain, prefix=".bundle-delivery-")
            try:
                for path, content in sorted(materials.items()):
                    tree.write(path, content)
                tree.sync_and_check()
                tree.write(_MANIFEST, raw)
                tree.sync_and_check()
                delivery_path = root / tree.name
            finally:
                # Incomplete copies are retained and lack an inspectable complete manifest.
                _close_tree(tree)
            return inspect_bundle_delivery(
                delivery_path, expected_delivery_sha256=hashlib.sha256(raw).hexdigest(),
            )
        finally:
            chain.close()
    except (_benchmark_files.BenchmarkFileError, CandidateWorkspaceError, OSError, TypeError, ValueError):
        _fail()
