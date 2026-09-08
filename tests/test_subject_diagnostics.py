import hashlib
import json
import os
from pathlib import Path

import pytest

from famou.subject_diagnostics import (
    SubjectDiagnosticContext,
    capture_subject_diagnostic_context,
    normalize_diagnostic,
    publish_diagnostic,
    read_bounded_file,
)


def _context(root: Path, *, deep: bool = False) -> SubjectDiagnosticContext:
    workspace = root / "attempt/subject"
    workspace.mkdir(parents=True)
    request = {
        "mode": "deep_evolution" if deep else "normal", "run_index": 1,
        "receipt_path": "receipts/002.json" if deep else "receipt.json",
        **({"round_index": 2} if deep else {}),
    }
    raw = json.dumps(request).encode()
    (workspace / "request.json").write_bytes(raw)
    return SubjectDiagnosticContext.from_request(workspace, request, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("invalid", [
    "missing", "json", "oversized", "nested", "extra", "identity", "mode", "round", "bool",
    "code", "status", "directory", "symlink", "dangling", "cycle", "fifo", "hardlink",
])
def test_invalid_sidecars_are_not_collected(tmp_path: Path, deep: bool, invalid: str) -> None:
    context = _context(tmp_path, deep=deep)
    payload = context.payload("model", "model_failed", 0, 0, None)
    source = context.workspace / context.sidecar
    source.parent.mkdir(exist_ok=True)
    if invalid == "missing":
        pass
    elif invalid in {"json", "oversized", "nested"}:
        source.write_text({"json": "{", "oversized": " " * 4097, "nested": "[" * 1500 + "]" * 1500}[invalid])
    elif invalid == "directory":
        source.mkdir()
    elif invalid in {"symlink", "dangling", "cycle", "hardlink"}:
        target = tmp_path / "private.json"
        target.write_text(json.dumps(payload))
        if invalid == "hardlink":
            os.link(target, source)
        else:
            source.symlink_to({"symlink": target, "dangling": tmp_path / "absent", "cycle": source}[invalid])
    elif invalid == "fifo":
        os.mkfifo(source)
    else:
        if invalid == "extra":
            payload["score"] = 1.0
        elif invalid == "identity":
            payload["request_sha256"] = "0" * 64
        elif invalid == "mode":
            payload["mode"] = "deep_evolution" if not deep else "normal"
        elif invalid == "round":
            payload["round_index"] = 3
        elif invalid == "bool":
            payload["model_turns"] = True
        elif invalid == "code":
            payload["code"] = "private-text-not-in-enum"
        elif invalid == "status":
            payload["http_status"] = 999
        source.write_text(json.dumps(payload))
    context.collect()
    assert not (context.workspace.parent / "diagnostics").exists()


@pytest.mark.parametrize("ancestor", ["source", "workspace", "destination"])
def test_symlink_ancestors_never_allow_diagnostic_reads_or_writes(tmp_path: Path, ancestor: str) -> None:
    context = _context(tmp_path, deep=True)
    payload = context.payload("runtime", "runtime_failed", 1, 0, None)
    external = tmp_path / "external"
    external.mkdir()
    (external / "002.failure.json").write_text(json.dumps(payload))
    if ancestor == "source":
        (context.workspace / "receipts").symlink_to(external, target_is_directory=True)
    else:
        publish_diagnostic(context.workspace, context.sidecar, payload)
        if ancestor == "workspace":
            context.workspace.rename(external / "saved-subject")
            context.workspace.symlink_to(external / "saved-subject", target_is_directory=True)
        else:
            (context.workspace.parent / "diagnostics").symlink_to(external, target_is_directory=True)
    context.collect()
    assert not (external / "subject-002-failure.json").exists()
    if ancestor != "destination":
        assert not (context.workspace.parent / "diagnostics").exists()


@pytest.mark.parametrize("destination", ["file", "directory", "fifo", "symlink", "dangling"])
def test_publication_refuses_all_existing_destinations(tmp_path: Path, destination: str) -> None:
    context = _context(tmp_path)
    payload = context.payload("tool", "tool_failed", 2, 1, None)
    source = context.workspace / context.sidecar
    if destination == "file":
        source.write_text("preserve existing evidence")
    elif destination == "directory":
        source.mkdir()
    elif destination == "fifo":
        os.mkfifo(source)
    else:
        target = tmp_path / "private"
        if destination == "symlink":
            target.write_text("private")
        source.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        publish_diagnostic(context.workspace, context.sidecar, payload)
    assert not list(context.workspace.glob(".subject-diagnostic-*"))
    if destination == "file":
        assert source.read_text() == "preserve existing evidence"
    if destination == "symlink":
        assert (tmp_path / "private").read_text() == "private"


def test_stale_same_request_sidecar_is_not_accepted_as_new_invocation_evidence(tmp_path: Path) -> None:
    context = _context(tmp_path)
    assert capture_subject_diagnostic_context(context.workspace, "request.json") == context
    publish_diagnostic(context.workspace, context.sidecar, context.payload("runtime", "step_limit", 4, 3, None))
    assert capture_subject_diagnostic_context(context.workspace, "request.json") is None


def test_bounded_reader_never_reads_an_entire_oversized_file(tmp_path: Path) -> None:
    context = _context(tmp_path)
    source = context.workspace / context.sidecar
    with source.open("wb") as stream:
        stream.truncate(1024 * 1024 * 1024)
    with pytest.raises(ValueError, match="bounded regular file"):
        read_bounded_file(context.workspace, context.sidecar)


def test_diagnostics_require_bounded_counters_and_fixed_vocabulary(tmp_path: Path) -> None:
    context = _context(tmp_path)
    payload = context.payload("runtime", "runtime_failed", 0, 0, None)
    assert normalize_diagnostic(payload) == payload
    for key, value in (("tool_steps", -1), ("model_turns", 1_000_001), ("stage", "secret"), ("run_index", False)):
        with pytest.raises(ValueError):
            normalize_diagnostic({**payload, key: value})
