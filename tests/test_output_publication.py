"""Fault boundaries for the complete evolved-output publication batch."""

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

from famou.algorithm import OutputSpec
from famou.models import Run
from famou.output_publication import (
    OutputPublicationError,
    OutputPublicationUncertain,
    publish_outputs,
    recover_outputs,
)
from famou.store import Store

SPECS = (
    OutputSpec("output/first.txt", "text"),
    OutputSpec("output/nested/second.txt", "text"),
)
CONTENTS = (b"first independently validated output\n", b"second validated output\n")
LIMIT = 1_000_000


class SimulatedCrash(BaseException):
    """Interrupt without running ordinary exception compensation."""


def _fixture(tmp_path: Path) -> tuple[Store, Run, Run, str]:
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run(
        "publish verified outputs",
        tmp_path / "parent",
        tasks=[
            {"id": "solve", "title": "Solve", "prompt": "solve", "depends_on": []},
            {"id": "other", "title": "Other", "prompt": "other", "depends_on": []},
        ],
    )
    child = store.create_run("evolve", tmp_path / "child")
    Path(parent.workspace).mkdir(parents=True, exist_ok=True)
    Path(child.workspace).mkdir(parents=True, exist_ok=True)
    owner = next(task.id for task in store.list_tasks(parent.id) if task.id == "solve")
    return store, parent, child, owner


def _publish(store: Store, parent: Run, child: Run, owner: str):
    return publish_outputs(
        store,
        parent,
        child.id,
        owner,
        list(zip(SPECS, CONTENTS, strict=True)),
        LIMIT,
    )


def _journal(parent: Run, child: Run) -> Path:
    identity = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
    return Path(parent.workspace) / ".evolved-output-publications" / identity / "journal.json"


def _paths(parent: Run) -> tuple[Path, ...]:
    return tuple(Path(parent.workspace) / spec.path for spec in SPECS)


def _assert_files(parent: Run) -> None:
    for path, expected in zip(_paths(parent), CONTENTS, strict=True):
        assert path.read_bytes() == expected


def _assert_no_files(parent: Run) -> None:
    assert all(not os.path.lexists(path) for path in _paths(parent))


def _snapshot(root: Path) -> dict[str, tuple]:
    result = {}
    for path in root.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            result[relative] = ("symlink", os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            result[relative] = ("file", info.st_dev, info.st_ino, path.read_bytes())
        else:
            result[relative] = ("node", info.st_mode)
    return result


def _crash_after_first_link(monkeypatch, store, parent, child, owner) -> None:
    original = os.link
    first = _paths(parent)[0]

    def link_then_crash(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == first:
            raise SimulatedCrash("process stopped after the first final link")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", link_then_crash)
        with pytest.raises(SimulatedCrash):
            _publish(store, parent, child, owner)
    assert first.read_bytes() == CONTENTS[0]
    assert not _paths(parent)[1].exists()
    assert _journal(parent, child).is_file()


def test_multiple_outputs_commit_as_one_batch_and_recover_idempotently(tmp_path: Path) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    promoted = _publish(store, parent, child, owner)

    assert isinstance(promoted, tuple)
    assert [row["path"] for row in promoted] == [spec.path for spec in SPECS]
    _assert_files(parent)
    rows = store.list_artifacts(parent.id)
    assert len(rows) == 2
    for spec, content, output in zip(SPECS, CONTENTS, promoted, strict=True):
        artifact = next(row for row in rows if row["id"] == output["artifact_id"])
        assert artifact["path"] == spec.path
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
        assert artifact["size"] == len(content)
        assert artifact["kind"] == "output"
        assert artifact["task_id"] == owner
    events = store.list_events(parent.id)
    promoted_events = [item for item in events if item["type"] == "evolved_outputs_promoted"]
    assert len(promoted_events) == 1
    assert promoted_events[0]["payload"] == {
        "evolution_run_id": child.id,
        "outputs": list(promoted),
    }
    assert len([event for event in events if event["type"] == "artifact_recorded"]) == 2
    assert recover_outputs(store, parent, child.id, SPECS) == "committed"
    assert recover_outputs(store, parent, child.id, SPECS) == "committed"
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


def test_no_journal_needs_no_recovery(tmp_path: Path) -> None:
    store, parent, child, _owner = _fixture(tmp_path)
    assert recover_outputs(store, parent, child.id, SPECS) is None
    _assert_no_files(parent)
    assert not _journal(parent, child).exists()


def test_second_link_failure_rolls_back_all_new_outputs(tmp_path: Path, monkeypatch) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    original = os.link
    second = _paths(parent)[1]
    events = store.list_events(parent.id)

    def fail_second_link(source, destination, *args, **kwargs):
        if Path(destination) == second:
            raise OSError("injected second output link failure")
        return original(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail_second_link)
        with pytest.raises(OutputPublicationError):
            _publish(store, parent, child, owner)

    _assert_no_files(parent)
    assert store.list_artifacts(parent.id) == []
    assert store.list_events(parent.id) == events
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"


@pytest.mark.parametrize("failure", ["second_artifact", "second_artifact_event", "promotion_event"])
def test_sql_failure_leaves_no_partial_rows_events_or_files(tmp_path: Path, failure: str) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    if failure == "second_artifact":
        target = "artifacts"
        condition = "NEW.path = 'output/nested/second.txt'"
    elif failure == "second_artifact_event":
        target = "events"
        condition = (
            "NEW.type = 'artifact_recorded' AND "
            "json_extract(NEW.payload, '$.path') = 'output/nested/second.txt'"
        )
    else:
        target = "events"
        condition = "NEW.type = 'evolved_outputs_promoted'"
    with store._connect() as connection:
        connection.execute(
            f"CREATE TRIGGER fail_publication BEFORE INSERT ON {target} WHEN {condition} "
            "BEGIN SELECT RAISE(ABORT, 'injected publication failure'); END"
        )
    events = store.list_events(parent.id)

    with pytest.raises(OutputPublicationError):
        _publish(store, parent, child, owner)

    _assert_no_files(parent)
    assert store.list_artifacts(parent.id) == []
    assert store.list_events(parent.id) == events
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"


@pytest.mark.parametrize("recorded", [False, True], ids=["file_only", "other_task_ledger"])
def test_matching_preexisting_output_is_reused_without_replacement(
    tmp_path: Path, recorded: bool
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    first = _paths(parent)[0]
    first.parent.mkdir(parents=True)
    first.write_bytes(CONTENTS[0])
    identity = (first.stat().st_dev, first.stat().st_ino)
    existing_id = None
    if recorded:
        other = next(task.id for task in store.list_tasks(parent.id) if task.id != owner)
        existing_id = store.add_artifact(
            parent.id, other, SPECS[0].path,
            hashlib.sha256(CONTENTS[0]).hexdigest(), len(CONTENTS[0]), "output",
        )

    result = _publish(store, parent, child, owner)

    _assert_files(parent)
    assert (first.stat().st_dev, first.stat().st_ino) == identity
    rows = store.list_artifacts(parent.id)
    assert len(rows) == 2
    if recorded:
        assert result[0]["artifact_id"] == existing_id
        assert next(row for row in rows if row["id"] == existing_id)["task_id"] == other
    assert recover_outputs(store, parent, child.id, SPECS) == "committed"


def test_rollback_preserves_matching_preexisting_file_and_ledger(tmp_path: Path) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    first = _paths(parent)[0]
    first.parent.mkdir(parents=True)
    first.write_bytes(CONTENTS[0])
    store.add_artifact(
        parent.id, owner, SPECS[0].path,
        hashlib.sha256(CONTENTS[0]).hexdigest(), len(CONTENTS[0]), "output",
    )
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)
    identity = first.stat().st_ino
    with store._connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_second BEFORE INSERT ON artifacts "
            "WHEN NEW.path = 'output/nested/second.txt' "
            "BEGIN SELECT RAISE(ABORT, 'second output failed'); END"
        )

    with pytest.raises(OutputPublicationError):
        _publish(store, parent, child, owner)

    assert first.read_bytes() == CONTENTS[0]
    assert first.stat().st_ino == identity
    assert not _paths(parent)[1].exists()
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"


def test_commit_success_followed_by_exception_is_confirmed_without_rollback(
    tmp_path: Path, monkeypatch
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    original = store.commit_output_publication

    def committed_then_exception(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("acknowledgement lost after commit")

    with monkeypatch.context() as patch:
        patch.setattr(store, "commit_output_publication", committed_then_exception)
        result = _publish(store, parent, child, owner)

    _assert_files(parent)
    assert len(result) == 2
    assert len(store.list_artifacts(parent.id)) == 2
    assert recover_outputs(store, parent, child.id, SPECS) == "committed"


@pytest.mark.parametrize("committed", [False, True], ids=["before_commit", "after_commit"])
def test_unavailable_commit_status_preserves_files_until_recovery(
    tmp_path: Path, monkeypatch, committed: bool
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    original_commit = store.commit_output_publication

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("database unavailable during reconciliation")

    with monkeypatch.context() as patch:
        def unknown_commit(*args, **kwargs):
            if committed:
                original_commit(*args, **kwargs)
            patch.setattr(store, "output_publication_committed", unavailable)
            raise sqlite3.OperationalError("commit outcome unavailable")

        patch.setattr(store, "commit_output_publication", unknown_commit)
        with pytest.raises(OutputPublicationUncertain):
            _publish(store, parent, child, owner)
        _assert_files(parent)
        assert _journal(parent, child).is_file()

    expected = "committed" if committed else "rolled_back"
    assert recover_outputs(store, parent, child.id, SPECS) == expected
    if committed:
        _assert_files(parent)
        assert len(store.list_artifacts(parent.id)) == 2
    else:
        _assert_no_files(parent)
        assert store.list_artifacts(parent.id) == []


def test_interrupted_first_link_recovers_without_partial_delivery(tmp_path: Path, monkeypatch) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    events = store.list_events(parent.id)
    _crash_after_first_link(monkeypatch, store, parent, child, owner)

    assert store.list_artifacts(parent.id) == []
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    _assert_no_files(parent)
    assert store.list_events(parent.id) == events


@pytest.mark.parametrize("committed", [False, True], ids=["prepared", "committed"])
def test_process_crash_at_database_boundary_reconciles_exact_batch(
    tmp_path: Path, monkeypatch, committed: bool
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    original = store.commit_output_publication

    def interrupted_commit(*args, **kwargs):
        if committed:
            original(*args, **kwargs)
        raise SimulatedCrash("database boundary process interruption")

    with monkeypatch.context() as patch:
        patch.setattr(store, "commit_output_publication", interrupted_commit)
        with pytest.raises(SimulatedCrash):
            _publish(store, parent, child, owner)
    _assert_files(parent)
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)
    expected = "committed" if committed else "rolled_back"
    assert recover_outputs(store, parent, child.id, SPECS) == expected
    assert recover_outputs(store, parent, child.id, SPECS) == expected
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events
    if committed:
        _assert_files(parent)
        assert len(rows) == 2
    else:
        _assert_no_files(parent)
        assert rows == []


@pytest.mark.parametrize("boundary", ["first_link", "after_commit"])
def test_native_process_exit_preserves_recoverable_publication(tmp_path: Path, boundary: str) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    script = r'''
import os
import sys
from pathlib import Path
from famou.algorithm import OutputSpec
from famou.output_publication import publish_outputs
from famou.store import Store

database, parent_id, child_id, owner, boundary = sys.argv[1:]
store = Store(database)
parent = store.get_run(parent_id)
assert parent is not None
specs = [OutputSpec("output/first.txt", "text"), OutputSpec("output/nested/second.txt", "text")]
contents = [b"first independently validated output\n", b"second validated output\n"]
if boundary == "first_link":
    original = os.link
    def crash_link(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == Path(parent.workspace) / specs[0].path:
            os._exit(73)
    os.link = crash_link
else:
    original = store.commit_output_publication
    def crash_commit(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(73)
    store.commit_output_publication = crash_commit
publish_outputs(store, parent, child_id, owner, list(zip(specs, contents)), 1000000)
raise AssertionError("injected process exit was not reached")
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(store.database), parent.id, child.id, owner, boundary],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == 73, completed.stderr
    assert _journal(parent, child).is_file()
    expected = "rolled_back" if boundary == "first_link" else "committed"
    assert recover_outputs(store, parent, child.id, SPECS) == expected
    assert recover_outputs(store, parent, child.id, SPECS) == expected
    if boundary == "first_link":
        _assert_no_files(parent)
        assert store.list_artifacts(parent.id) == []
    else:
        _assert_files(parent)
        assert len(store.list_artifacts(parent.id)) == 2


@pytest.mark.parametrize("drift", ["target_replaced", "stage_replaced", "journal_corrupt"])
def test_uncommitted_recovery_preflights_all_evidence_before_any_deletion(
    tmp_path: Path, monkeypatch, drift: str
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _crash_after_first_link(monkeypatch, store, parent, child, owner)
    first, second = _paths(parent)
    journal = _journal(parent, child)
    if drift == "target_replaced":
        second.parent.mkdir(parents=True, exist_ok=True)
        second.write_bytes(b"unrelated external content\n")
    elif drift == "stage_replaced":
        linked = next(
            path for path in journal.parent.rglob("*")
            if path.is_file() and not path.is_symlink()
            and path.stat().st_ino == first.stat().st_ino
            and path.stat().st_dev == first.stat().st_dev
        )
        linked.unlink()
        linked.write_bytes(CONTENTS[0])
    else:
        journal.write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    files = _snapshot(Path(parent.workspace))
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)

    with pytest.raises(OutputPublicationError):
        recover_outputs(store, parent, child.id, SPECS)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


@pytest.mark.parametrize("node", ["symlink", "broken_symlink", "directory", "fifo"])
def test_unsafe_journal_is_rejected_without_cleanup(
    tmp_path: Path, monkeypatch, node: str
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _crash_after_first_link(monkeypatch, store, parent, child, owner)
    journal = _journal(parent, child)
    original = journal.read_bytes()
    journal.unlink()
    if node == "symlink":
        referent = tmp_path / "external-journal.json"
        referent.write_bytes(original)
        journal.symlink_to(referent)
    elif node == "broken_symlink":
        journal.symlink_to(tmp_path / "absent-journal.json")
    elif node == "directory":
        journal.mkdir()
    else:
        os.mkfifo(journal)
    files = _snapshot(Path(parent.workspace))
    events = store.list_events(parent.id)

    with pytest.raises(OutputPublicationError):
        recover_outputs(store, parent, child.id, SPECS)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == []
    assert store.list_events(parent.id) == events


def test_committed_recovery_rejects_output_drift_without_changing_ledger(tmp_path: Path) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _publish(store, parent, child, owner)
    _paths(parent)[1].write_bytes(b"external drift\n")
    files = _snapshot(Path(parent.workspace))
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)

    with pytest.raises(OutputPublicationError):
        recover_outputs(store, parent, child.id, SPECS)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


@pytest.mark.parametrize("failure", ["conflicting_file", "conflicting_ledger", "duplicate_ledger", "budget"])
def test_preflight_failure_publishes_no_new_file_or_row(tmp_path: Path, failure: str) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    first = _paths(parent)[0]
    if failure == "conflicting_file":
        first.parent.mkdir(parents=True)
        first.write_bytes(b"preexisting user data\n")
    elif failure in {"conflicting_ledger", "duplicate_ledger"}:
        digest = "0" * 64 if failure == "conflicting_ledger" else hashlib.sha256(CONTENTS[0]).hexdigest()
        for _ in range(2 if failure == "duplicate_ledger" else 1):
            store.add_artifact(parent.id, owner, SPECS[0].path, digest, len(CONTENTS[0]), "output")
    files = {path: path.read_bytes() for path in _paths(parent) if path.exists()}
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)
    maximum = 1 if failure == "budget" else LIMIT

    with pytest.raises(OutputPublicationError):
        publish_outputs(
            store, parent, child.id, owner,
            list(zip(SPECS, CONTENTS, strict=True)), maximum,
        )

    assert {path: path.read_bytes() for path in _paths(parent) if path.exists()} == files
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


def test_recovery_rejects_changed_contract_projection_without_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _crash_after_first_link(monkeypatch, store, parent, child, owner)
    changed = (OutputSpec(SPECS[0].path, "json"), SPECS[1])
    files = _snapshot(Path(parent.workspace))

    with pytest.raises(OutputPublicationError):
        recover_outputs(store, parent, child.id, changed)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == []


def test_recovery_rejects_journal_identity_change_without_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _crash_after_first_link(monkeypatch, store, parent, child, owner)
    journal = _journal(parent, child)
    payload = json.loads(journal.read_text(encoding="utf-8"))
    payload["parent_run_id"] = "foreign-parent"
    journal.write_text(json.dumps(payload), encoding="utf-8")
    files = _snapshot(Path(parent.workspace))

    with pytest.raises(OutputPublicationError):
        recover_outputs(store, parent, child.id, SPECS)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == []


def test_interrupted_rollback_can_resume_after_the_first_unlink(tmp_path: Path, monkeypatch) -> None:
    store, parent, child, owner = _fixture(tmp_path)

    def crash_before_commit(*args, **kwargs):
        raise SimulatedCrash("stop before database commit")

    with monkeypatch.context() as patch:
        patch.setattr(store, "commit_output_publication", crash_before_commit)
        with pytest.raises(SimulatedCrash):
            _publish(store, parent, child, owner)
    _assert_files(parent)
    original = Path.unlink
    first, second = _paths(parent)

    def unlink_then_crash(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path == first:
            raise SimulatedCrash("stop during rollback")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", unlink_then_crash)
        with pytest.raises(SimulatedCrash):
            recover_outputs(store, parent, child.id, SPECS)
    assert not first.exists()
    assert second.read_bytes() == CONTENTS[1]

    original_sync = os.fsync
    synced_directories = set()

    def sync(descriptor):
        current = os.fstat(descriptor)
        if stat.S_ISDIR(current.st_mode):
            synced_directories.add((current.st_dev, current.st_ino))
        original_sync(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    first_parent = first.parent.stat()
    assert (first_parent.st_dev, first_parent.st_ino) in synced_directories
    assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    _assert_no_files(parent)
    assert store.list_artifacts(parent.id) == []


@pytest.mark.parametrize("change", ["content", "owner", "empty"])
@pytest.mark.parametrize("state", ["committed", "prepared"])
def test_publication_replay_rejects_changed_request_under_the_same_identity(
    tmp_path: Path, monkeypatch, change: str, state: str,
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    if state == "prepared":
        _crash_after_first_link(monkeypatch, store, parent, child, owner)
    else:
        _publish(store, parent, child, owner)
    files = _snapshot(Path(parent.workspace))
    rows = store.list_artifacts(parent.id)
    events = store.list_events(parent.id)
    if change == "content":
        changed = [(SPECS[0], b"different newly prepared result\n"), (SPECS[1], CONTENTS[1])]
    elif change == "empty":
        changed = []
    else:
        changed = list(zip(SPECS, CONTENTS, strict=True))
        owner = next(task.id for task in store.list_tasks(parent.id) if task.id != owner)

    with pytest.raises(OutputPublicationError):
        publish_outputs(store, parent, child.id, owner, changed, LIMIT)

    assert _snapshot(Path(parent.workspace)) == files
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


@pytest.mark.parametrize("removed", ["transaction", "root"])
def test_missing_journal_directory_cannot_downgrade_a_committed_publication(
    tmp_path: Path, removed: str,
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    _publish(store, parent, child, owner)
    shutil.rmtree(_journal(parent, child).parent if removed == "transaction" else parent.workspace)
    rows, events = store.list_artifacts(parent.id), store.list_events(parent.id)
    with pytest.raises(OutputPublicationUncertain):
        recover_outputs(store, parent, child.id, SPECS)
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events


@pytest.mark.parametrize("fail_sync", [False, True])
def test_reused_output_is_synced_before_commit_and_preserved_on_sync_failure(
    tmp_path: Path, monkeypatch, fail_sync: bool,
) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    first = _paths(parent)[0]
    first.parent.mkdir()
    first.write_bytes(CONTENTS[0])
    identity = first.stat()
    original_sync, original_commit = os.fsync, store.commit_output_publication
    synced = False

    def sync(descriptor):
        nonlocal synced
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            if fail_sync:
                raise OSError("fixture existing file sync failed")
            synced = True
        original_sync(descriptor)

    def commit(*args, **kwargs):
        assert synced
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(store, "commit_output_publication", commit)
    if fail_sync:
        with pytest.raises(OutputPublicationError, match="output_publication_rolled_back"):
            _publish(store, parent, child, owner)
        assert not _paths(parent)[1].exists()
        assert store.list_artifacts(parent.id) == []
        assert recover_outputs(store, parent, child.id, SPECS) == "rolled_back"
    else:
        _publish(store, parent, child, owner)
        assert synced
        assert recover_outputs(store, parent, child.id, SPECS) == "committed"
    assert first.read_bytes() == CONTENTS[0]
    assert (first.stat().st_dev, first.stat().st_ino) == (identity.st_dev, identity.st_ino)


@pytest.mark.parametrize("path", ["output/FIRST.txt", "output/first.txt/child.txt"])
def test_optional_path_alias_is_rejected_even_before_a_journal_exists(tmp_path: Path, path: str) -> None:
    store, parent, child, _owner = _fixture(tmp_path)
    specs = (SPECS[0], OutputSpec(path, "text", required=False))
    files = _snapshot(parent.workspace)
    with pytest.raises(OutputPublicationUncertain):
        recover_outputs(store, parent, child.id, specs)
    assert _snapshot(parent.workspace) == files


def test_cross_volume_destination_is_rejected_before_staging(tmp_path: Path, monkeypatch) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    output = parent.workspace / "output"
    output.mkdir()
    original = os.stat

    def stat_on_other_volume(path, *args, **kwargs):
        current = original(path, *args, **kwargs)
        if path == output:
            values = list(current)
            values[2] += 1
            return os.stat_result(values)
        return current

    monkeypatch.setattr(os, "stat", stat_on_other_volume)
    with pytest.raises(OutputPublicationError, match="output_publication_cross_volume"):
        _publish(store, parent, child, owner)
    assert not _journal(parent, child).parent.exists()
    _assert_no_files(parent)
    assert store.list_artifacts(parent.id) == []


@pytest.mark.parametrize("drift", ["foreign_owner", "partial_reserved_row", "orphan_event"])
def test_invalid_existing_ledger_is_rejected_before_any_final_link(tmp_path: Path, drift: str) -> None:
    store, parent, child, owner = _fixture(tmp_path)
    first = _paths(parent)[0]
    first.parent.mkdir()
    first.write_bytes(CONTENTS[0])
    digest = hashlib.sha256(CONTENTS[0]).hexdigest()
    reserved = "artifact-output-publication-" + hashlib.sha256(
        f"{parent.id}\0{child.id}\0{SPECS[0].path}".encode()
    ).hexdigest()
    if drift == "orphan_event":
        store.append_event(parent.id, "artifact_recorded", {
            "artifact_id": reserved, "path": SPECS[0].path,
            "sha256": digest, "size": len(CONTENTS[0]),
        }, task_id=owner)
    else:
        task_id = store.list_tasks(child.id)[0].id if drift == "foreign_owner" else owner
        artifact = store.add_artifact(
            parent.id, task_id, SPECS[0].path, digest, len(CONTENTS[0]), "output",
        )
        if drift == "partial_reserved_row":
            with store._connect() as connection:
                connection.execute("UPDATE artifacts SET id = ? WHERE id = ?", (reserved, artifact))
    rows, events = store.list_artifacts(parent.id), store.list_events(parent.id)
    with pytest.raises(OutputPublicationError):
        _publish(store, parent, child, owner)
    assert first.read_bytes() == CONTENTS[0]
    assert not _paths(parent)[1].exists()
    assert store.list_artifacts(parent.id) == rows
    assert store.list_events(parent.id) == events
