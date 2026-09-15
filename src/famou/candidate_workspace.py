"""Materialize a verified multi-file candidate into an isolated private directory."""
from __future__ import annotations
import hashlib, os
from collections.abc import Mapping
from pathlib import Path
from . import _benchmark_files as _files
from .candidate_bundle import CandidateBundleError, CandidateSourceBundle, CandidateSourceFile, parse_candidate_source_bundle, validate_candidate_source_bundle, verify_candidate_source_bundle
from .candidate_workspace_plan import CandidateWorkspaceError, CandidateWorkspacePlan, WORKSPACE_PLAN_PROTOCOL, WORKSPACE_PLAN_SCHEMA_VERSION, build_candidate_workspace_plan, candidate_file_table_sha256, parse_candidate_workspace_plan, validate_candidate_workspace_plan
from ._candidate_workspace_io import DirectoryChain, PrivateTree

class VerifiedCandidateWorkspace:
    __slots__ = ("workspace_path", "bundle_sha256", "contract_sha256", "entrypoint", "file_count", "total_bytes", "file_table_sha256")
    def __init__(self, workspace_path: Path, verified) -> None:
        self.workspace_path=workspace_path; self.bundle_sha256=verified.bundle_sha256; self.contract_sha256=verified.bundle.contract_sha256; self.entrypoint=verified.bundle.entrypoint; self.file_count=verified.file_count; self.total_bytes=verified.total_bytes; self.file_table_sha256=candidate_file_table_sha256(verified.bundle)
    def to_dict(self):
        return {"status":"materialized","bundle_sha256":self.bundle_sha256,"contract_sha256":self.contract_sha256,"entrypoint":self.entrypoint,"file_count":self.file_count,"total_bytes":self.total_bytes,"file_table_sha256":self.file_table_sha256}

def _read_source(root: Path, item: CandidateSourceFile) -> bytes:
    try: data = _files.read_regular_file(_files.absolute_path(root / item.path), item.size, exact_size=True)
    except _files.BenchmarkFileError as exc: raise CandidateWorkspaceError("candidate_workspace_" + ("source_missing" if exc.reason == "missing" else "source_changed")) from None
    if len(data) != item.size or hashlib.sha256(data).hexdigest() != item.sha256: raise CandidateWorkspaceError("candidate_workspace_source_changed")
    try: data.decode("utf-8")
    except UnicodeDecodeError: raise CandidateWorkspaceError("candidate_workspace_source_encoding_invalid") from None
    if b"\x00" in data: raise CandidateWorkspaceError("candidate_workspace_source_encoding_invalid")
    return data

def materialize_candidate_source_bundle(bundle: CandidateSourceBundle | Mapping[str, object] | str | os.PathLike[str], *, source_root: str | os.PathLike[str], workspace_root: str | os.PathLike[str], contract_sha256: str | None = None, expected_bundle_sha256: str | None = None) -> VerifiedCandidateWorkspace:
    if contract_sha256 is None: raise CandidateWorkspaceError("candidate_workspace_contract_required")
    try: source_path=Path(_files.absolute_path(source_root)); source_chain=DirectoryChain(source_path,"candidate_workspace_source_unsafe")
    except Exception: raise CandidateWorkspaceError("candidate_workspace_source_unsafe") from None
    try: parent_path=Path(_files.absolute_path(workspace_root)); parent_chain=DirectoryChain(parent_path,"candidate_workspace_workspace_root_unsafe")
    except Exception: source_chain.close(); raise CandidateWorkspaceError("candidate_workspace_workspace_root_unsafe") from None
    try:
        if source_path == parent_path or source_path.is_relative_to(parent_path) or parent_path.is_relative_to(source_path): raise CandidateWorkspaceError("candidate_workspace_workspace_root_unsafe")
        parsed=validate_candidate_source_bundle(bundle if isinstance(bundle,CandidateSourceBundle) else parse_candidate_source_bundle(bundle))
        try:
            verified=verify_candidate_source_bundle(parsed,source_root=source_path,contract_sha256=contract_sha256,expected_bundle_sha256=expected_bundle_sha256)
        except CandidateBundleError as exc:
            suffix = exc.code.removeprefix("candidate_bundle_")
            if suffix in {"source_unsafe", "source_missing", "source_changed", "source_encoding_invalid"}:
                raise CandidateWorkspaceError("candidate_workspace_" + suffix) from None
            raise CandidateWorkspaceError("candidate_workspace_materialization_failed") from None
        tree=PrivateTree(parent_chain)
        try:
            for item in verified.bundle.files: source_chain.check(); tree.check_root(); tree.write(item.path,_read_source(source_path,item))
            tree.sync_and_check(); return VerifiedCandidateWorkspace(parent_path/tree.name,verified)
        except OSError as exc:
            try: tree.cleanup()
            except BaseException: raise CandidateWorkspaceError("candidate_workspace_cleanup_failed") from exc
            raise CandidateWorkspaceError("candidate_workspace_destination_write_failed") from None
        except BaseException as exc:
            try: tree.cleanup()
            except BaseException: raise CandidateWorkspaceError("candidate_workspace_cleanup_failed") from exc
            if isinstance(exc,CandidateWorkspaceError): raise
            raise CandidateWorkspaceError("candidate_workspace_materialization_failed") from None
        finally: tree.close()
    finally: source_chain.close(); parent_chain.close()

__all__=["WORKSPACE_PLAN_PROTOCOL","WORKSPACE_PLAN_SCHEMA_VERSION","CandidateWorkspaceError","CandidateWorkspacePlan","VerifiedCandidateWorkspace","build_candidate_workspace_plan","candidate_file_table_sha256","materialize_candidate_source_bundle","parse_candidate_workspace_plan","validate_candidate_workspace_plan"]
