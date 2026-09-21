"""Read-only inventory preserves retained evidence and never authorizes recovery."""

import gc
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_materialization_delivery import (
    _delete_output_batch,
    _delete_terminal_batch,
    _directory,
    _interrupt,
    _marker,
    _materialize,
    _output_directory,
    _terminal,
)
from test_materialization_delivery import (
    _fixture as _delivery_fixture,
)
from test_materialization_execution import _delete_execution_batch
from test_materialization_launch import _attempt, _intent, _interrupt_after_intent

import lunar_evolution.controller as controller_module
import lunar_evolution.materialization_delivery as delivery
import lunar_evolution.materialization_execution as execution
import lunar_evolution.materialization_launch as launch
import lunar_evolution.materialization_publication as terminal
import lunar_evolution.output_publication as outputs
from lunar_evolution import cli
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import CommandCandidateRunner
from lunar_evolution.store import Store

STAGES = {"launch", "execution", "delivery", "outputs", "terminal"}
STAGE_STATES = {"absent", "present", "incomplete", "invalid", "unavailable"}
FILE_STATES = {"absent", "present", "invalid", "unsafe", "unavailable"}
SENSITIVE = "private-goal-command-stdout-stderr-token-DO-NOT-PRINT"


def _fixture(tmp_path: Path, outcome: str = "success"):
    fixture = _delivery_fixture(tmp_path, outcome)
    # Creation of a conversational run records a path but defers its directory.
    # These inventory fixtures provide both roots before launching or failing.
    Path(fixture[1].workspace).mkdir(parents=True, exist_ok=True)
    return fixture


def _diagnose(database: Path, parent_id: str, child_id: str) -> dict:
    from lunar_evolution.materialization_diagnostics import diagnose_materialization

    return diagnose_materialization(database, parent_id, child_id)


def _source_snapshot(root: Path) -> dict[str, tuple]:
    """Include directory entries and mtime, never open a symlink or special node."""
    snapshot = {}

    def visit(path: Path) -> None:
        metadata = path.lstat()
        key = path.relative_to(root).as_posix()
        identity = (
            metadata.st_dev, metadata.st_ino, metadata.st_mode,
            metadata.st_size, metadata.st_mtime_ns,
        )
        if stat.S_ISREG(metadata.st_mode):
            snapshot[key] = (*identity, path.read_bytes())
        elif stat.S_ISLNK(metadata.st_mode):
            snapshot[key] = (*identity, os.readlink(path))
        elif stat.S_ISDIR(metadata.st_mode):
            children = sorted(path.iterdir())
            snapshot[key] = (*identity, tuple(child.name for child in children))
            for child in children:
                visit(child)
        else:
            snapshot[key] = identity

    visit(root)
    return snapshot


def _deny_mutations(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("read-only diagnostics entered runtime, storage initialization or recovery")

    for owner, name in (
        (Store, "_connect"), (Store, "initialize"), (Config, "ensure"),
        (LocalController, "__init__"), (LocalController, "materialize_evolved_outputs"),
        (LocalController, "_promote_evolved_outputs"), (CommandCandidateRunner, "run"),
        (cli, "_config"), (cli, "_controller"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    for module, names in (
        (launch, ("materialization_lock", "prepare_launch_intent", "inspect_launch_intent")),
        (execution, ("recover_materialization_execution", "publish_materialization_execution")),
        (delivery, ("prepare_materialization_delivery", "complete_materialization_delivery")),
        (outputs, ("recover_outputs", "recover_output_batch", "publish_outputs", "_locked")),
        (terminal, ("recover_materialization_result", "publish_materialization_result", "_locked")),
    ):
        for name in names:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
            if hasattr(controller_module, name):
                monkeypatch.setattr(controller_module, name, forbidden)


def _assert_report(report: dict, parent_id: str, child_id: str) -> None:
    assert report["schema_version"] == "1"
    assert report["parent_run_id"] == parent_id
    assert report["evolution_run_id"] == child_id
    assert report["status"] in {"observed", "attention_required", "busy", "unavailable"}
    assert report["recovery_eligibility"] == "not_assessed"
    assert set(report["stages"]) == STAGES
    assert isinstance(report["issues"], list)
    assert isinstance(report["next_step"], str) and report["next_step"]
    for stage in report["stages"].values():
        assert stage["state"] in STAGE_STATES
        assert isinstance(stage["files"], dict)
        assert isinstance(stage["events"], dict)
        assert isinstance(stage["artifacts"], int) and stage["artifacts"] >= 0
        assert isinstance(stage["issues"], list)
        assert all(isinstance(count, int) and count >= 0 for count in stage["events"].values())
        for observed in stage["files"].values():
            assert observed["state"] in FILE_STATES
            assert set(observed) <= {"state", "size", "sha256", "issue"}
    encoded = json.dumps(report)
    for forbidden in ('"can_resume"', '"recoverable"', '"committed"', '"successful"', SENSITIVE):
        assert forbidden not in encoded


def _preserved_report(tmp_path, monkeypatch, controller, parent, child) -> dict:
    # The fixture's ordinary Store connections must settle before measuring source files.
    gc.collect()
    _deny_mutations(monkeypatch)
    before = _source_snapshot(tmp_path)
    report = _diagnose(controller.config.database, parent.id, child.id)
    _assert_report(report, parent.id, child.id)
    assert str(tmp_path) not in json.dumps(report)
    assert _source_snapshot(tmp_path) == before
    return report


@pytest.mark.parametrize("outcome", ["success", "failed", "timed_out", "validation_failed"])
def test_complete_materialization_is_observed_without_mutating_sources(
    tmp_path: Path, monkeypatch, outcome: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    _materialize(controller, parent, child, result)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] in {"observed", "attention_required"}
    if outcome == "success":
        assert report["status"] == "observed"
    for stage, key, path in (
        ("launch", "intent", _intent(child)),
        ("execution", "attempt_execution", _attempt(child, result) / "execution.json"),
        ("delivery", "plan", _directory(child) / "plan.json"),
        ("terminal", "marker", _marker(child)),
    ):
        observed = report["stages"][stage]["files"][key]
        assert observed["state"] == "present"
        assert observed["size"] == path.stat().st_size
        assert observed["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"


@pytest.mark.parametrize("boundary", [
    "execution_prepared", "execution_committed", "plan", "output_commit", "promoter_return",
    "terminal_prepared", "terminal_committed", "completion", "completion_link",
])
def test_interrupted_materialization_reports_inventory_without_recovery(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] in {"observed", "attention_required"}
    assert report["stages"]["execution"]["files"]["journal"]["state"] == "present"
    assert report["stages"]["launch"]["files"]["intent"]["state"] == "present"
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"


def test_launch_only_inventory_does_not_execute_or_complete_attempt(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt_after_intent(monkeypatch, controller, parent, child, result)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["stages"]["launch"]["files"]["intent"]["state"] == "present"
    assert report["stages"]["execution"]["files"]["attempt_execution"]["state"] == "absent"
    assert not (_attempt(child, result) / "execution-count.txt").exists()


def test_unstarted_materialization_does_not_create_directories_or_locks(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, _ = _fixture(tmp_path)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] in {"observed", "attention_required"}
    assert report["stages"]["launch"]["files"]["intent"]["state"] == "absent"
    assert not _intent(child).parent.exists()
    assert not (Path(child.workspace) / "evolution/.materialization.lock").exists()


@pytest.mark.parametrize("fragment", ["filesystem_only", "database_only", "missing_completion"])
def test_delivery_fragments_are_preserved_without_repair(
    tmp_path: Path, monkeypatch, fragment: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    if fragment == "filesystem_only":
        with controller.store._connect() as connection:
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND type = ?",
                (child.id, "materialization_delivery_prepared"),
            )
    elif fragment == "database_only":
        (_directory(child) / "plan.json").unlink()
    else:
        (_directory(child) / "completed.json").unlink()
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"]["delivery"]["issues"]


@pytest.mark.parametrize("stage", ["execution", "outputs", "terminal"])
def test_retained_completion_with_missing_ledger_is_not_reconstructed(
    tmp_path: Path, monkeypatch, stage: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    if stage == "execution":
        _delete_execution_batch(controller, child)
    elif stage == "outputs":
        _delete_output_batch(controller, parent, child)
    else:
        _delete_terminal_batch(controller, parent, child)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"][stage]["issues"]


def test_legacy_execution_and_terminal_evidence_stays_read_only(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    _intent(child).unlink()
    shutil.rmtree(_intent(child).parent / ".execution-publication")
    shutil.rmtree(_directory(child))
    with controller.store._connect() as connection:
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type IN (?, ?, ?, ?)",
            (child.id, "materialization_launch_intended", "materialization_execution_prepared",
             "materialization_execution_committed", "materialization_delivery_prepared"),
        )
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] in {"observed", "attention_required"}
    assert report["stages"]["launch"]["files"]["intent"]["state"] == "absent"
    assert report["stages"]["terminal"]["files"]["marker"]["state"] == "present"


def _protocol_path(stage: str, parent, child) -> tuple[str, Path]:
    return {
        "launch": ("intent", _intent(child)),
        "execution": ("journal", _intent(child).parent / ".execution-publication/journal.json"),
        "delivery": ("plan", _directory(child) / "plan.json"),
        "outputs": ("journal", _output_directory(parent, child) / "journal.json"),
        "terminal": ("journal", _terminal(child) / "journal.json"),
    }[stage]


@pytest.mark.parametrize("stage", sorted(STAGES))
@pytest.mark.parametrize("node", ["symlink", "broken_symlink", "directory", "fifo"])
def test_unsafe_protocol_nodes_are_reported_without_opening_or_replacing_them(
    tmp_path: Path, monkeypatch, stage: str, node: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    key, path = _protocol_path(stage, parent, child)
    path.unlink()
    if node == "symlink":
        target = tmp_path / "private-target.txt"
        target.write_text(SENSITIVE)
        path.symlink_to(target)
    elif node == "broken_symlink":
        path.symlink_to(tmp_path / "missing-target")
    elif node == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"][stage]["files"][key]["state"] == "unsafe"


@pytest.mark.parametrize("stage", sorted(STAGES))
@pytest.mark.parametrize("payload", [b"{broken", b"[]", b'{"schema_version":"1","schema_version":"2"}'])
def test_malformed_protocol_json_is_reported_without_raw_payload(
    tmp_path: Path, monkeypatch, stage: str, payload: bytes,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    key, path = _protocol_path(stage, parent, child)
    path.write_bytes(payload)
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"][stage]["files"][key]["state"] == "invalid"


def test_oversize_protocol_record_is_bounded_and_preserved(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    (_directory(child) / "plan.json").write_text(json.dumps({"private": SENSITIVE * 50_000}))
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"]["delivery"]["files"]["plan"]["state"] == "invalid"


def test_receipt_digest_mismatch_is_an_observation_not_repair(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    completed = _directory(child) / "completed.json"
    payload = json.loads(completed.read_bytes())
    payload["plan_sha256"] = "0" * 64
    completed.write_text(json.dumps(payload))
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "attention_required"
    assert report["stages"]["delivery"]["issues"]


def test_private_ledger_and_execution_contents_are_never_returned(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET goal = ?", (SENSITIVE,))
        row = connection.execute(
            "SELECT id, payload FROM events WHERE run_id = ? AND type = ?",
            (child.id, "materialization_delivery_prepared"),
        ).fetchone()
        payload = json.loads(row["payload"])
        payload["private"] = SENSITIVE
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), row["id"]))
    controller.store.append_event(child.id, SENSITIVE, {"private": SENSITIVE})
    execution_path = _attempt(child, result) / "execution.json"
    payload = json.loads(execution_path.read_bytes())
    payload.update(stdout=SENSITIVE, stderr=SENSITIVE, error=SENSITIVE, command=[SENSITIVE])
    execution_path.write_text(json.dumps(payload))
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert SENSITIVE not in json.dumps(report)


@pytest.mark.parametrize("which", ["parent", "child"])
def test_missing_workspace_is_unavailable_without_recreating_it(
    tmp_path: Path, monkeypatch, which: str,
) -> None:
    controller, parent, child, _ = _fixture(tmp_path)
    shutil.rmtree(Path((parent if which == "parent" else child).workspace))
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["status"] == "unavailable"


@pytest.mark.parametrize("which", ["parent", "child"])
def test_unknown_run_ids_do_not_initialize_or_disclose_storage(
    tmp_path: Path, monkeypatch, which: str,
) -> None:
    controller, parent, child, _ = _fixture(tmp_path)
    parent_id = "missing-parent" if which == "parent" else parent.id
    child_id = "missing-child" if which == "child" else child.id
    gc.collect()
    _deny_mutations(monkeypatch)
    before = _source_snapshot(tmp_path)
    report = _diagnose(controller.config.database, parent_id, child_id)
    _assert_report(report, parent_id, child_id)
    assert report["status"] == "unavailable"
    assert str(tmp_path) not in json.dumps(report)
    assert _source_snapshot(tmp_path) == before


@pytest.mark.parametrize("lock_stage", ["launch", "outputs", "terminal"])
def test_existing_lock_is_never_recreated_when_missing(
    tmp_path: Path, monkeypatch, lock_stage: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    lock = _lock_path(lock_stage, parent, child)
    lock.unlink()
    report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
    assert report["stages"][lock_stage]["files"]["lock"]["state"] == "absent"
    assert not lock.exists()


def _lock_path(stage: str, parent, child) -> Path:
    return {
        "launch": Path(child.workspace) / "evolution/.materialization.lock",
        "outputs": Path(parent.workspace) / ".evolved-output-publications/.lock",
        "terminal": _intent(child).parent / ".terminal-publication.lock",
    }[stage]


@pytest.mark.parametrize("lock_stage", ["launch", "outputs", "terminal"])
def test_active_writer_lock_returns_busy_and_preserves_evidence(
    tmp_path: Path, monkeypatch, lock_stage: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    program = (
        "import fcntl, os, sys\n"
        "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "sys.stdin.read()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(_lock_path(lock_stage, parent, child))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        import select

        assert select.select([process.stdout], [], [], 10)[0], "writer did not acquire lock"
        assert process.stdout.readline().strip() == "locked"
        report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
        assert report["status"] == "busy"
    finally:
        process.communicate(timeout=10)
        assert process.returncode == 0


def test_committed_uncheckpointed_wal_is_observed_without_source_sqlite_open(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    gc.collect()
    database = controller.config.database
    connect = sqlite3.connect
    connection = connect(database)
    try:
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute(
            "INSERT INTO events (id, run_id, task_id, type, payload, created_at) "
            "SELECT ?, run_id, task_id, type, payload, created_at FROM events "
            "WHERE run_id = ? AND type = ?",
            ("diagnostic-wal-receipt", child.id, "materialization_delivery_prepared"),
        )
        connection.commit()
        assert Path(str(database) + "-wal").stat().st_size > 32
        opened = []

        def copy_only(path, *args, **kwargs):
            assert str(database) not in str(path), "diagnostics opened the source SQLite database"
            opened.append(str(path))
            return connect(path, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", copy_only)
        report = _preserved_report(tmp_path, monkeypatch, controller, parent, child)
        assert opened
        assert report["stages"]["delivery"]["events"]["materialization_delivery_prepared"] == 2
    finally:
        connection.close()


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("existing_home", [False, True])
def test_cli_missing_database_does_not_initialize_home(
    tmp_path: Path, monkeypatch, capsys, json_output: bool, existing_home: bool,
) -> None:
    home = tmp_path / "uninitialized-home"
    if existing_home:
        home.mkdir()
    _deny_mutations(monkeypatch)
    before = _source_snapshot(tmp_path)
    args = ["diagnose-materialization", "parent", "child", "--home", str(home)]
    if json_output:
        args.append("--json")
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out
    assert str(home) not in captured.out + captured.err
    if json_output:
        report = json.loads(captured.out)
        _assert_report(report, "parent", "child")
        assert report["status"] == "unavailable"
    assert _source_snapshot(tmp_path) == before


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("attention", [False, True])
def test_cli_report_exit_zero_means_inspected_and_never_initializes_runtime(
    tmp_path: Path, monkeypatch, capsys, json_output: bool, attention: bool,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    if attention:
        (_directory(child) / "completed.json").unlink()
    gc.collect()
    _deny_mutations(monkeypatch)
    before = _source_snapshot(tmp_path)
    args = ["diagnose-materialization", parent.id, child.id, "--home", str(controller.config.home)]
    if json_output:
        args.append("--json")
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert captured.out
    assert str(tmp_path) not in captured.out + captured.err
    assert SENSITIVE not in captured.out + captured.err
    if json_output:
        report = json.loads(captured.out)
        _assert_report(report, parent.id, child.id)
        assert report["status"] == ("attention_required" if attention else "observed")
    assert _source_snapshot(tmp_path) == before
