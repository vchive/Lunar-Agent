"""Copy admission-bound candidate inputs into a fresh private local directory.

Staging observes bytes and owns only its newly allocated tree. It neither starts an execution
nor creates a durable receipt, and the returned directory remains mutable by its caller.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from . import _benchmark_files as _files
from ._candidate_workspace_io import DirectoryChain, PrivateTree, identity
from .candidate_execution import (
    CandidateExecutionAdmission,
    CandidateExecutionError,
    CandidateExecutionInput,
    admit_candidate_execution,
    validate_candidate_execution_admission,
)
from .candidate_workspace_plan import CandidateWorkspaceError, CandidateWorkspacePlan


class CandidateInputStagingError(ValueError):
    """A fixed public code that never includes local paths, bytes, or OS exception text."""

    _CODES = frozenset({
        "input_missing", "input_unsafe", "input_changed", "staging_root_unsafe",
        "destination_changed", "destination_write_failed", "cleanup_failed", "invalid",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_input_staging_") if isinstance(code, str) else ""
        self.code = "candidate_input_staging_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise CandidateInputStagingError(code)


@dataclass(frozen=True)
class StagedCandidateExecutionInputs:
    """Detached admission metadata plus a local, caller-owned input directory."""

    admission: CandidateExecutionAdmission
    input_path: Path

    def __post_init__(self) -> None:
        admission = validate_candidate_execution_admission(self.admission)
        if not isinstance(self.input_path, Path):
            _fail("invalid")
        object.__setattr__(self, "admission", admission)

    @property
    def admission_sha256(self) -> str:
        return self.admission.digest()

    @property
    def plan_sha256(self) -> str:
        return self.admission.workspace_plan_sha256

    @property
    def workspace_plan_sha256(self) -> str:
        return self.plan_sha256

    @property
    def bundle_sha256(self) -> str:
        return self.admission.bundle_sha256

    @property
    def contract_sha256(self) -> str:
        return self.admission.contract_sha256

    @property
    def input_count(self) -> int:
        return len(self.admission.inputs)

    @property
    def total_input_bytes(self) -> int:
        return sum(item.size for item in self.admission.inputs)

    def to_dict(self) -> dict[str, object]:
        checked = StagedCandidateExecutionInputs(self.admission, self.input_path)
        return {
            "status": "staged", "admission_sha256": checked.admission_sha256,
            "plan_sha256": checked.plan_sha256, "bundle_sha256": checked.bundle_sha256,
            "contract_sha256": checked.contract_sha256, "input_count": checked.input_count,
            "total_input_bytes": checked.total_input_bytes,
        }


def _open_root(value: str | os.PathLike[str], *, source: bool) -> tuple[Path, DirectoryChain]:
    try:
        root = _files.absolute_path(value)
        chain = DirectoryChain(root, "source_changed" if source else "destination_changed")
        return root, chain
    except FileNotFoundError:
        _fail("input_missing" if source else "staging_root_unsafe")
    except (OSError, _files.BenchmarkFileError, CandidateWorkspaceError):
        _fail("input_unsafe" if source else "staging_root_unsafe")


def _check_source(chain: DirectoryChain) -> None:
    try:
        chain.check()
    except (OSError, CandidateWorkspaceError):
        _fail("input_changed")


def _check_disjoint(source: DirectoryChain, staging: DirectoryChain) -> None:
    # Compare held identities, including every ancestor, rather than lexical path spelling.
    # Shared ancestors are fine; either root appearing within the other chain is overlap.
    try:
        source_ids = {identity(os.fstat(descriptor)) for descriptor in source.fds}
        staging_ids = {identity(os.fstat(descriptor)) for descriptor in staging.fds}
        if identity(os.fstat(source.fd)) in staging_ids or identity(os.fstat(staging.fd)) in source_ids:
            _fail("staging_root_unsafe")
    except OSError:
        _fail("staging_root_unsafe")


def _read_input(root: Path, item: CandidateExecutionInput) -> bytes:
    try:
        content = _files.read_regular_file(
            _files.absolute_path(root / item.target), item.size, exact_size=True,
        )
    except _files.BenchmarkFileError as exc:
        _fail({"missing": "input_missing", "unsafe": "input_unsafe"}.get(exc.reason, "input_changed"))
    except OSError:
        _fail("input_changed")
    if len(content) != item.size or hashlib.sha256(content).hexdigest() != item.sha256:
        _fail("input_changed")
    return content


def _verify_destination(root: Path, item: CandidateExecutionInput) -> None:
    try:
        content = _files.read_regular_file(
            _files.absolute_path(root / item.target), item.size, exact_size=True,
        )
    except (OSError, _files.BenchmarkFileError):
        _fail("destination_changed")
    if len(content) != item.size or hashlib.sha256(content).hexdigest() != item.sha256:
        _fail("destination_changed")


def _raise_failure(failure: BaseException) -> NoReturn:
    if isinstance(failure, (CandidateInputStagingError, CandidateExecutionError)):
        raise failure from None
    if isinstance(failure, CandidateWorkspaceError):
        code = failure.code.removeprefix("candidate_workspace_")
        if code == "destination_conflict":
            code = "destination_write_failed"
        raise CandidateInputStagingError(code) from None
    if isinstance(failure, OSError):
        raise CandidateInputStagingError("destination_write_failed") from None
    if isinstance(failure, Exception):
        raise CandidateInputStagingError("invalid") from None
    # An interruption is re-raised only after identity-bounded cleanup and descriptor release.
    raise failure from None


def stage_candidate_execution_inputs(
    admission: CandidateExecutionAdmission | Mapping[str, object] | str | bytes, *,
    plan: CandidateWorkspacePlan | Mapping[str, object],
    input_root: str | os.PathLike[str], staging_root: str | os.PathLike[str],
    expected_admission_sha256: str | None = None,
    expected_plan_sha256: str | None = None,
    expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
) -> StagedCandidateExecutionInputs:
    """Revalidate a complete declaration, then stage fresh bytes without executing anything."""
    verified = admit_candidate_execution(
        admission, plan=plan, expected_admission_sha256=expected_admission_sha256,
        expected_plan_sha256=expected_plan_sha256, expected_bundle_sha256=expected_bundle_sha256,
        expected_contract_sha256=expected_contract_sha256,
    )
    parsed = verified.admission
    source_chain: DirectoryChain | None = None
    parent_chain: DirectoryChain | None = None
    tree: PrivateTree | None = None
    failure: BaseException | None = None
    result: StagedCandidateExecutionInputs | None = None
    try:
        source, source_chain = _open_root(input_root, source=True)
        parent, parent_chain = _open_root(staging_root, source=False)
        _check_disjoint(source_chain, parent_chain)
        # The admission caps this complete buffer at 16 MiB. Read only declared inputs and
        # finish source-byte checks before allocating a destination, including for empty sets.
        contents: list[bytes] = []
        for item in parsed.inputs:
            _check_source(source_chain)
            contents.append(_read_input(source, item))
            _check_source(source_chain)
        _check_source(source_chain)
        parent_chain.check()
        tree = PrivateTree(parent_chain, prefix=".candidate-inputs-")
        destination = parent / tree.name
        for item, content in zip(parsed.inputs, contents, strict=True):
            _check_source(source_chain)
            tree.check_root()
            tree.write(item.target, content)
        # PrivateTree's metadata checks alone cannot detect a same-size corrupted write.
        for item in parsed.inputs:
            _check_source(source_chain)
            tree.check_root()
            _verify_destination(destination, item)
            tree.check_root()
            _check_source(source_chain)
        tree.sync_and_check()
        _check_source(source_chain)
        result = StagedCandidateExecutionInputs(parsed, destination)
    except BaseException as exc:  # noqa: BLE001 - an interruption still owns a partial tree
        failure = exc

    if failure is not None and tree is not None:
        try:
            tree.cleanup()
        except BaseException:  # noqa: BLE001 - no cleanup error may expose paths or OS text
            failure = CandidateInputStagingError("cleanup_failed")
    for handle in (tree, parent_chain, source_chain):
        if handle is not None:
            try:
                handle.close()
            except BaseException:  # noqa: BLE001 - release all other descriptors even on interruption
                # A failed close makes further cleanup through that descriptor ambiguous.
                failure = CandidateInputStagingError("cleanup_failed" if tree is not None else "invalid")
    if failure is not None:
        _raise_failure(failure)
    if result is None:
        _fail("invalid")
    return result


__all__ = [
    "CandidateInputStagingError", "StagedCandidateExecutionInputs",
    "stage_candidate_execution_inputs",
]
