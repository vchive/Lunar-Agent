"""Export a bounded, sanitized snapshot of materialization evidence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from .diagnostic_snapshot import DiagnosticSnapshotError, diagnostic_snapshot
from .materialization_diagnostics import diagnose_materialization

MAX_BUNDLE_BYTES = 256 * 1024
_INVALID = "materialization_evidence_export_invalid"


class MaterializationEvidenceExportError(ValueError):
    """The source or destination cannot be exported safely."""


def _encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _safe_destination(path: Path, workspaces: list[Path]) -> tuple[Path, Path]:
    raw = path.expanduser()
    if not raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
        raise MaterializationEvidenceExportError(_INVALID)
    destination = raw
    parent = destination.parent
    try:
        parent_info = os.lstat(parent)
    except OSError as exc:
        raise MaterializationEvidenceExportError(_INVALID) from exc
    if not stat.S_ISDIR(parent_info.st_mode) or parent.is_symlink():
        raise MaterializationEvidenceExportError(_INVALID)
    current = parent
    while current != current.parent:
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) and current not in {Path("/var"), Path("/tmp")}:
            raise MaterializationEvidenceExportError(_INVALID)
        if not stat.S_ISLNK(info.st_mode) and not stat.S_ISDIR(info.st_mode):
            raise MaterializationEvidenceExportError(_INVALID)
        current = current.parent
    resolved = destination.resolve(strict=False)
    for workspace in workspaces:
        root = workspace.resolve(strict=False)
        if resolved == root or root in resolved.parents:
            raise MaterializationEvidenceExportError(_INVALID)
    if destination.exists() or destination.is_symlink() or (parent / ("." + destination.name + ".tmp")).exists():
        raise MaterializationEvidenceExportError(_INVALID)
    return destination, parent


def _envelopes(snapshot: dict) -> tuple[list[dict], list[dict]]:
    events = []
    for row in snapshot["events"]:
        payload = row["payload"]
        encoded = _encode(payload)
        events.append({
            "id": row["id"], "run_id": row["run_id"], "task_id": row["task_id"],
            "type": row["type"], "payload_size": len(encoded), "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        })
    artifacts = []
    for row in snapshot["artifacts"]:
        artifacts.append({
            "id": row["id"], "run_id": row["run_id"], "task_id": row["task_id"],
            "kind": row["kind"], "size": row["size"], "sha256": row["sha256"],
        })
    return events, artifacts


def export_materialization_evidence(database: Path, parent_id: str, child_id: str, output: Path) -> dict:
    """Write one no-clobber sanitized bundle; never mutate source run state."""
    try:
        snapshot = diagnostic_snapshot(database, parent_id, child_id)
        report = diagnose_materialization(database, parent_id, child_id, _snapshot_data=snapshot)
        if report["status"] in {"busy", "unavailable"}:
            raise MaterializationEvidenceExportError("materialization_evidence_source_unavailable")
        runs = {row["id"]: row for row in snapshot["runs"]}
        if set(runs) != {parent_id, child_id}:
            raise MaterializationEvidenceExportError("materialization_evidence_source_unavailable")
        destination, parent = _safe_destination(output, [Path(runs[parent_id]["workspace"]), Path(runs[child_id]["workspace"])])
        events, artifacts = _envelopes(snapshot)
        bundle = {
            "schema_version": "1", "parent_run_id": parent_id, "evolution_run_id": child_id,
            "report": report, "events": events, "artifacts": artifacts,
        }
        content = _encode(bundle)
        if len(content) > MAX_BUNDLE_BYTES:
            raise MaterializationEvidenceExportError("materialization_evidence_export_limit")
        temporary = parent / ("." + destination.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("export write made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {"schema_version": "1", "status": "exported", "path": str(destination), "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    except MaterializationEvidenceExportError:
        raise
    except DiagnosticSnapshotError as exc:
        raise MaterializationEvidenceExportError("materialization_evidence_source_unavailable") from exc
    except (OSError, TypeError, ValueError, KeyError, RecursionError) as exc:
        raise MaterializationEvidenceExportError(_INVALID) from exc
