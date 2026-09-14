"""Portable materialization evidence exports are bounded, sanitized and no-clobber."""

import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from test_materialization_diagnostics import _fixture, _materialize

from famou import cli
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import CommandCandidateRunner
from famou.materialization_evidence_bundle import (
    MaterializationEvidenceExportError,
    export_materialization_evidence,
)
from famou.store import Store

SENSITIVE = "bundle-secret-goal-command-payload-DO-NOT-LEAK"


def _bundle(controller, parent, child, destination: Path) -> dict:
    return export_materialization_evidence(
        controller.config.database, parent.id, child.id, destination,
    )


def _snapshot(root: Path) -> dict[str, tuple]:
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        key = "." if path == root else path.relative_to(root).as_posix()
        identity = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)
        if stat.S_ISREG(info.st_mode):
            result[key] = (*identity, path.read_bytes())
        elif stat.S_ISLNK(info.st_mode):
            result[key] = (*identity, os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            result[key] = (*identity, tuple(sorted(item.name for item in path.iterdir())))
        else:
            result[key] = identity
    return result


def _deny_runtime(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("evidence export initialized storage, runtime or recovery")

    monkeypatch.setattr(Store, "_connect", forbidden)
    monkeypatch.setattr(Store, "initialize", forbidden)
    monkeypatch.setattr(Config, "ensure", forbidden)
    monkeypatch.setattr(LocalController, "__init__", forbidden)
    monkeypatch.setattr(CommandCandidateRunner, "run", forbidden)
    monkeypatch.setattr(cli, "_config", forbidden)
    monkeypatch.setattr(cli, "_controller", forbidden)


def test_stable_export_is_sanitized_and_contains_only_allowlisted_envelopes(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    _deny_runtime(monkeypatch)
    source_roots = (Path(controller.config.home), Path(child.workspace))
    before = tuple(_snapshot(root) for root in source_roots)
    destination = tmp_path / "review" / "evidence.json"
    destination.parent.mkdir()
    payload = _bundle(controller, parent, child, destination)
    assert payload["status"] == "exported"
    bundle = json.loads(destination.read_bytes())
    assert set(bundle) == {"schema_version", "parent_run_id", "evolution_run_id", "report", "events", "artifacts"}
    assert bundle["report"]["recovery_eligibility"] == "not_assessed"
    for event in bundle["events"]:
        assert set(event) == {"id", "run_id", "task_id", "type", "payload_size", "payload_sha256"}
    for artifact in bundle["artifacts"]:
        assert set(artifact) == {"id", "run_id", "task_id", "kind", "size", "sha256"}
    encoded = destination.read_text()
    assert SENSITIVE not in encoded
    assert str(parent.workspace) not in encoded and str(child.workspace) not in encoded
    assert payload["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert tuple(_snapshot(root) for root in source_roots) == before


def test_repeated_exports_to_different_paths_are_byte_identical(tmp_path: Path) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    first, second = output_dir / "one.json", output_dir / "two.json"
    _bundle(controller, parent, child, first)
    _bundle(controller, parent, child, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("kind", ["existing", "temporary", "symlink"])
def test_destination_is_no_clobber_and_safe(tmp_path: Path, kind: str) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    destination = tmp_path / "exports" / "evidence.json"
    destination.parent.mkdir()
    if kind == "existing":
        destination.write_text("incumbent")
    elif kind == "temporary":
        (destination.parent / ".evidence.json.tmp").write_text("partial")
    else:
        destination.symlink_to(tmp_path / "target")
    with pytest.raises(MaterializationEvidenceExportError):
        _bundle(controller, parent, child, destination)
    assert not destination.is_file() or destination.read_bytes() != b"{\n"


def test_destination_inside_either_workspace_is_rejected(tmp_path: Path) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    for workspace in (Path(parent.workspace), Path(child.workspace)):
        destination = workspace / "evidence.json"
        with pytest.raises(MaterializationEvidenceExportError):
            _bundle(controller, parent, child, destination)
        assert not destination.exists()


def test_missing_source_does_not_create_destination(tmp_path: Path) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    destination = tmp_path / "exports" / "evidence.json"
    destination.parent.mkdir()
    with pytest.raises(MaterializationEvidenceExportError):
        export_materialization_evidence(tmp_path / "missing.db", parent.id, child.id, destination)
    assert not destination.exists()


@pytest.mark.parametrize("lock_stage", ["launch", "outputs", "terminal"])
def test_busy_source_does_not_create_destination(tmp_path: Path, lock_stage: str) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    lock = {
        "launch": Path(child.workspace) / "evolution/.materialization.lock",
        "outputs": Path(parent.workspace) / ".evolved-output-publications/.lock",
        "terminal": Path(child.workspace) / "evolution/materialization/.terminal-publication.lock",
    }[lock_stage]
    program = "import fcntl,sys; fd=open(sys.argv[1],'r'); fcntl.flock(fd,fcntl.LOCK_EX); print('locked',flush=True); input()"
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(lock)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True,
    )
    try:
        import select

        assert select.select([process.stdout], [], [], 10)[0]
        destination = tmp_path / "exports" / "evidence.json"
        destination.parent.mkdir()
        with pytest.raises(MaterializationEvidenceExportError):
            _bundle(controller, parent, child, destination)
        assert not destination.exists()
    finally:
        process.communicate("\n", timeout=10)


def test_source_snapshot_is_unchanged_and_sensitive_payload_is_not_exported(tmp_path: Path) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET goal = ?", (SENSITIVE,))
        connection.execute(
            "INSERT INTO events(id, run_id, task_id, type, payload, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (f"event-{uuid.uuid4().hex}", child.id, None, "private", json.dumps({"payload": SENSITIVE}), "2026-09-14T00:00:00+00:00"),
        )
    source_roots = (Path(controller.config.home), Path(child.workspace))
    before = tuple(_snapshot(root) for root in source_roots)
    destination = tmp_path / "exports" / "evidence.json"
    destination.parent.mkdir()
    _bundle(controller, parent, child, destination)
    assert tuple(_snapshot(root) for root in source_roots) == before
    assert SENSITIVE not in destination.read_text()


def test_cli_export_dispatches_before_config_and_emits_json(tmp_path: Path, monkeypatch, capsys) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    _deny_runtime(monkeypatch)
    destination = tmp_path / "exports" / "evidence.json"
    destination.parent.mkdir()
    code = cli.main([
        "export-materialization-evidence", parent.id, child.id,
        "--home", str(controller.config.home), "--output", str(destination), "--json",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "exported"
    assert destination.exists()


def test_ledger_change_during_report_prevents_export(tmp_path: Path, monkeypatch) -> None:
    import famou.materialization_diagnostics as diagnostics

    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    original = diagnostics.diagnostic_snapshot

    def changed(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        snapshot["events"] = []
        return snapshot

    monkeypatch.setattr(diagnostics, "diagnostic_snapshot", changed)
    destination = tmp_path / "exports" / "evidence.json"
    destination.parent.mkdir()
    with pytest.raises(MaterializationEvidenceExportError):
        _bundle(controller, parent, child, destination)
    assert not destination.exists()
