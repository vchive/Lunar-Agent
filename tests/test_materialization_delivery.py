"""Continue a prepared delivery without reexecution or repair of completed corruption."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_evolved_output_materialization import (
    _contract,
    _counted_materialization_source,
    _evolution_fixture,
)
from test_materialization_execution import _delete_execution_batch
from test_materialization_launch import _attempt, _deny_runner, _intent
from test_materialization_launch_durability import _descriptor_names_path
from test_materialization_publication import (
    SimulatedCrash,
    _database_snapshot,
    _filesystem_snapshot,
    _forbid_execution_and_promotion,
)

import lunar_evolution.materialization_delivery as delivery
from lunar_evolution import output_publication
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.evolution import EvolutionError

PREPARED = "materialization_delivery_prepared"


def _fixture(tmp_path: Path, outcome: str = "success", *, contract=None):
    source = _counted_materialization_source(output=outcome == "success")
    if outcome == "failed":
        source += "raise SystemExit(7)\n"
    elif outcome == "timed_out":
        source += "import time\ntime.sleep(10)\n"
    return _evolution_fixture(tmp_path, source, contract=contract)


def _materialize(controller, parent, child, result, *, contract=None, timeout=1):
    return controller.materialize_evolved_outputs(
        parent.id, child.id, contract or _contract(), result, timeout_seconds=timeout,
    )


def _directory(child) -> Path:
    return Path(child.workspace) / "evolution/materialization/.delivery-publication"


def _terminal(child) -> Path:
    return _directory(child).parent / ".terminal-publication"


def _marker(child) -> Path:
    return _directory(child).parent / "result.json"


def _output_directory(parent, child) -> Path:
    suffix = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
    return Path(parent.workspace) / ".evolved-output-publications" / suffix


def _events(controller, child):
    return [event for event in controller.store.list_events(child.id) if event["type"] == PREPARED]


def _identity(child) -> dict:
    intent = json.loads(_intent(child).read_bytes())
    return {key: value for key, value in intent.items() if key not in {"runner_sha256", "timeout_seconds"}}


def _assert_count_one(child, result) -> None:
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"


def _assert_no_terminal(controller, parent, child) -> None:
    assert not _marker(child).exists()
    assert not any(row["kind"] == "evolved_materialization" for row in controller.store.list_artifacts(child.id))
    assert not any(event["type"] == "evolved_candidate_materialized" for event in controller.store.list_events(parent.id))


def _interrupt(monkeypatch, controller, parent, child, result, boundary: str, *, contract=None) -> None:
    methods = {
        "execution_prepared": "prepare_materialization_execution",
        "execution_committed": "commit_materialization_execution",
        "plan": "record_materialization_delivery",
        "output_commit": "commit_output_publication",
        "terminal_prepared": "prepare_materialization_publication",
        "terminal_committed": "commit_materialization_publication",
    }
    with monkeypatch.context() as patch:
        if boundary in methods:
            method = methods[boundary]
            original = getattr(controller.store, method)

            def committed_then_crash(*args, **kwargs):
                original(*args, **kwargs)
                raise SimulatedCrash("delivery interrupted at " + boundary)

            patch.setattr(controller.store, method, committed_then_crash)
        elif boundary == "promoter_return":
            original = controller._promote_evolved_outputs

            def promoted_then_crash(*args, **kwargs):
                original(*args, **kwargs)
                raise SimulatedCrash("outputs published but terminal not prepared")

            patch.setattr(controller, "_promote_evolved_outputs", promoted_then_crash)
        elif boundary == "completion":
            def before_complete(*args, **kwargs):
                raise SimulatedCrash("terminal completed before delivery receipt")

            patch.setattr(delivery, "_write_complete", before_complete)
        else:
            original = os.link

            def link_then_crash(source, destination, *args, **kwargs):
                original(source, destination, *args, **kwargs)
                if Path(destination) == _directory(child) / "completed.json":
                    raise SimulatedCrash("delivery completion linked before directory sync")

            patch.setattr(os, "link", link_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result, contract=contract)
    _assert_count_one(child, result)


def _replay_complete(monkeypatch, controller, parent, child, result, *, status="succeeded", promote=False, contract=None):
    _deny_runner(monkeypatch)
    if not promote:
        _forbid_execution_and_promotion(monkeypatch, controller)
    payload = _materialize(controller, parent, child, result, contract=contract)
    assert payload["status"] == status
    assert json.loads(_marker(child).read_bytes()) == payload
    assert (_directory(child) / "completed.json").is_file()
    assert len(_events(controller, child)) == 1
    _assert_count_one(child, result)
    assert len([event for event in controller.store.list_events(parent.id) if event["type"] == "evolved_candidate_materialized"]) == 1
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result, contract=contract, timeout=7) == payload
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
    return payload


def _reject_without_writes(monkeypatch, controller, parent, child, result) -> None:
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)
    for _ in range(2):
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger
    _assert_count_one(child, result)


def _delete_output_batch(controller, parent, child) -> None:
    rows = [row for row in controller.store.list_artifacts(parent.id) if row["kind"] == "output"]
    artifact_ids = {row["id"] for row in rows}
    events = [
        event for event in controller.store.list_events(parent.id)
        if event["type"] in {"evolved_outputs_promoted", "output_publication_committed"}
        and event["payload"].get("evolution_run_id") == child.id
        or event["type"] == "artifact_recorded" and event["payload"].get("artifact_id") in artifact_ids
    ]
    with controller.store._connect() as connection:
        for row in rows:
            connection.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
        for event in events:
            connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))


def _delete_terminal_batch(controller, parent, child, *, prepared=False) -> None:
    rows = [row for row in controller.store.list_artifacts(child.id) if row["kind"] == "evolved_materialization"]
    artifact_ids = {row["id"] for row in rows}
    events = [
        event for run in (parent, child) for event in controller.store.list_events(run.id)
        if event["type"] in {"evolved_candidate_materialized", "materialization_publication_committed"}
        or prepared and event["type"] == "materialization_publication_prepared"
        or event["type"] == "artifact_recorded" and event["payload"].get("artifact_id") in artifact_ids
    ]
    with controller.store._connect() as connection:
        for row in rows:
            connection.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
        for event in events:
            connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))


@pytest.mark.parametrize("boundary", ["execution_prepared", "execution_committed", "plan"])
@pytest.mark.parametrize("outcome", ["success", "failed", "timed_out", "validation_failed"])
def test_complete_execution_can_resume_verification_and_delivery_without_runner(
    tmp_path: Path, monkeypatch, boundary: str, outcome: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    _assert_no_terminal(controller, parent, child)
    payload = _replay_complete(
        monkeypatch, controller, parent, child, result,
        status="succeeded" if outcome == "success" else "failed", promote=outcome == "success",
    )
    assert bool(payload["outputs"]) is (outcome == "success")
    if outcome != "success":
        assert not _output_directory(parent, child).exists()
        assert payload["error"]


@pytest.mark.parametrize("boundary", ["output_commit", "promoter_return", "terminal_prepared", "terminal_committed", "completion", "completion_link"])
def test_committed_outputs_resume_exact_terminal_without_promoter(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    outputs = next(event["payload"]["outputs"] for event in controller.store.list_events(parent.id) if event["type"] == "evolved_outputs_promoted")
    payload = _replay_complete(monkeypatch, controller, parent, child, result)
    assert payload["outputs"] == outputs


def test_plan_registration_postcommit_exception_keeps_success(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = controller.store.record_materialization_delivery

    def committed_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("receipt committed but its caller did not observe a normal return")

    monkeypatch.setattr(controller.store, "record_materialization_delivery", committed_then_raise)
    assert _materialize(controller, parent, child, result)["status"] == "succeeded"
    _replay_complete(monkeypatch, controller, parent, child, result)


def test_failed_plan_transaction_leaves_fs_only_evidence_and_no_outputs(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)

    def reject(*args, **kwargs):
        raise sqlite3.OperationalError("injected delivery receipt rejection")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "record_materialization_delivery", reject)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
    assert (_directory(child) / "plan.json").is_file()
    assert not _events(controller, child)
    assert not _output_directory(parent, child).exists()
    _assert_no_terminal(controller, parent, child)
    _reject_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("committed", [False, True])
def test_unknown_output_commit_never_becomes_false_terminal_failure(
    tmp_path: Path, monkeypatch, committed: bool,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_commit = controller.store.commit_output_publication
    original_probe = controller.store.output_publication_committed
    unknown = False

    def uncertain_commit(*args, **kwargs):
        nonlocal unknown
        if committed:
            original_commit(*args, **kwargs)
        unknown = True
        raise OSError("injected unknown output commit")

    def unqueryable(*args, **kwargs):
        if unknown:
            raise sqlite3.OperationalError("output status unavailable")
        return original_probe(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_output_publication", uncertain_commit)
        patch.setattr(controller.store, "output_publication_committed", unqueryable)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
    assert unknown
    _assert_no_terminal(controller, parent, child)
    payload = _replay_complete(
        monkeypatch, controller, parent, child, result, status="succeeded" if committed else "failed",
    )
    if not committed:
        assert payload["error"] == "output_publication_rolled_back"
        assert payload["outputs"] == []


def test_crash_after_uncommitted_output_link_recovers_rollback_as_terminal_failure(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = os.link
    target = Path(parent.workspace) / "output/routes.csv"

    def linked_then_crash(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == target:
            raise SimulatedCrash("output path appeared before the atomic database batch")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", linked_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert target.is_file()
    _assert_no_terminal(controller, parent, child)
    payload = _replay_complete(monkeypatch, controller, parent, child, result, status="failed")
    assert payload["error"] == "output_publication_rolled_back"
    assert payload["outputs"] == []
    assert not target.exists()
    assert (_output_directory(parent, child) / "rolled-back.json").is_file()


def test_known_output_sql_rollback_finishes_failure_once(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    with controller.store._connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_delivery_output BEFORE INSERT ON events "
            "WHEN NEW.type = 'evolved_outputs_promoted' "
            "BEGIN SELECT RAISE(ABORT, 'injected output commit rejection'); END"
        )
    payload = _materialize(controller, parent, child, result)
    assert payload["status"] == "failed"
    assert payload["error"] == "output_publication_rolled_back"
    assert payload["outputs"] == []
    assert not (Path(parent.workspace) / "output/routes.csv").exists()
    _replay_complete(monkeypatch, controller, parent, child, result, status="failed")


@pytest.mark.parametrize("publication", ["output", "terminal"])
def test_incomplete_subprotocol_preparation_is_not_recreated_from_delivery_plan(
    tmp_path: Path, monkeypatch, publication: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    with monkeypatch.context() as patch:
        if publication == "terminal":
            def before_terminal_preparation(*args, **kwargs):
                raise SimulatedCrash("terminal staging exists without a prepared database receipt")

            patch.setattr(controller.store, "prepare_materialization_publication", before_terminal_preparation)
        else:
            original = output_publication._write_marker

            def before_output_journal(directory, name, payload):
                if name == "journal.json":
                    raise SimulatedCrash("output staging exists before its journal was written")
                return original(directory, name, payload)

            patch.setattr(output_publication, "_write_marker", before_output_journal)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert (_directory(child) / "plan.json").is_file()
    if publication == "terminal":
        assert (_terminal(child) / "journal.json").is_file()
        assert not any(event["type"] == "materialization_publication_prepared" for event in controller.store.list_events(child.id))
    else:
        assert (_output_directory(parent, child) / "00.blob").is_file()
        assert not (_output_directory(parent, child) / "journal.json").exists()
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    _assert_no_terminal(controller, parent, child)


def test_changed_pending_output_batch_is_rejected_before_any_safe_rollback(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = os.link
    target = Path(parent.workspace) / "output/routes.csv"

    def linked_then_crash(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == target:
            raise SimulatedCrash("retain an uncommitted output link")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", linked_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    # Keep the 088 stage, final hardlink, inode and journal internally consistent, while their
    # bytes disagree with the immutable 092 plan. Its metadata check must precede rollback.
    content = b"item_id,route_id\n1,B\n"
    target.write_bytes(content)
    journal_path = _output_directory(parent, child) / "journal.json"
    journal = json.loads(journal_path.read_bytes())
    journal["entries"][0]["output"].update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert target.read_bytes() == content
    assert not (_output_directory(parent, child) / "rolled-back.json").exists()


@pytest.mark.parametrize("boundary", ["terminal_prepared", "completion"])
def test_advanced_terminal_evidence_prevents_rolling_back_deleted_output_commit(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    _delete_output_batch(controller, parent, child)
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert (Path(parent.workspace) / "output/routes.csv").is_file()
    assert not (_output_directory(parent, child) / "rolled-back.json").exists()


@pytest.mark.parametrize("missing", ["terminal_artifact", "terminal_event", "terminal_batch", "output_batch", "output_file", "plan_file", "plan_directory", "plan_event"])
def test_completed_delivery_rejects_missing_records_without_any_reconstruction(
    tmp_path: Path, monkeypatch, missing: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    if missing == "terminal_batch":
        _delete_terminal_batch(controller, parent, child)
    elif missing == "output_batch":
        _delete_output_batch(controller, parent, child)
    elif missing == "output_file":
        (Path(parent.workspace) / "output/routes.csv").unlink()
    elif missing == "plan_file":
        (_directory(child) / "plan.json").unlink()
    elif missing == "plan_directory":
        shutil.rmtree(_directory(child))
    else:
        with controller.store._connect() as connection:
            if missing == "terminal_artifact":
                connection.execute("DELETE FROM artifacts WHERE run_id = ? AND kind = 'evolved_materialization'", (child.id,))
            else:
                run_id, event_type = (child.id, PREPARED) if missing == "plan_event" else (parent.id, "evolved_candidate_materialized")
                connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (run_id, event_type))
    _reject_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("retained", ["filesystem", "database"])
def test_delivery_preparation_prevents_091_from_rebuilding_deleted_execution(
    tmp_path: Path, monkeypatch, retained: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "plan")
    _delete_execution_batch(controller, child)
    execution_directory = _directory(child).parent / ".execution-publication"
    for name in ("completed.json", ".completed.json.tmp"):
        (execution_directory / name).unlink(missing_ok=True)
    if retained == "filesystem":
        with controller.store._connect() as connection:
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, PREPARED))
    else:
        shutil.rmtree(_directory(child))
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert not any(row["kind"] == "evolved_candidate_execution" for row in controller.store.list_artifacts(child.id))


@pytest.mark.parametrize("receipt", ["missing", "temporary"])
def test_intact_terminal_can_finish_delivery_completion_without_database_writes(
    tmp_path: Path, monkeypatch, receipt: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    completed = _directory(child) / "completed.json"
    if receipt == "temporary":
        completed.rename(_directory(child) / ".completed.json.tmp")
    else:
        completed.unlink()
    ledger = _database_snapshot(controller, parent, child)
    _replay_complete(monkeypatch, controller, parent, child, result)
    assert _database_snapshot(controller, parent, child) == ledger


def test_temporary_delivery_completion_forbids_recreating_terminal_batch(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    (_directory(child) / "completed.json").rename(_directory(child) / ".completed.json.tmp")
    _delete_terminal_batch(controller, parent, child)
    _reject_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("name", ["plan.json", ".plan.json.tmp", "completed.json", ".completed.json.tmp"])
@pytest.mark.parametrize("node", ["directory", "symlink", "broken_symlink", "fifo", "duplicate_key", "nonfinite", "partial", "oversized"])
def test_delivery_plan_and_receipt_abnormal_nodes_are_never_repaired(
    tmp_path: Path, monkeypatch, name: str, node: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "plan")
    path = _directory(child) / name
    if path.exists():
        path.unlink()
    if node == "directory":
        path.mkdir()
    elif node in {"symlink", "broken_symlink"}:
        target = tmp_path / "external-plan"
        if node == "symlink":
            target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
    elif node == "fifo":
        os.mkfifo(path)
    else:
        text = {"duplicate_key": '{"schema_version":"1","schema_version":"1"}', "nonfinite": '{"size":NaN}', "partial": '{"incomplete":', "oversized": " " * (128 * 1024)}[node]
        path.write_text(text, encoding="utf-8")
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert not _output_directory(parent, child).exists()


@pytest.mark.parametrize("drift", ["attempt_output", "attempt_output_missing", "candidate", "execution", "launch", "plan_identity", "plan_owner", "duplicate_plan_event"])
def test_prepared_delivery_rejects_changed_authority_and_validation_before_output_mutation(
    tmp_path: Path, monkeypatch, drift: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "plan")
    attempt = _attempt(child, result)
    if drift == "attempt_output":
        (attempt / "output/routes.csv").write_text("item_id,route_id\n1,B\n", encoding="utf-8")
    elif drift == "attempt_output_missing":
        (attempt / "output/routes.csv").unlink()
    elif drift == "candidate":
        (attempt / "candidate.py").write_text("# changed selected source", encoding="utf-8")
    elif drift == "execution":
        (attempt / "execution.json").write_text("{}", encoding="utf-8")
    elif drift == "launch":
        _intent(child).unlink()
    elif drift == "plan_identity":
        path = _directory(child) / "plan.json"
        value = json.loads(path.read_bytes())
        value["parent_run_id"] = "different-parent"
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    else:
        event = _events(controller, child)[0]
        with controller.store._connect() as connection:
            if drift == "plan_owner":
                connection.execute("UPDATE events SET task_id = NULL WHERE id = ?", (event["id"],))
            else:
                controller.store._append_event(connection, child.id, event["task_id"], PREPARED, event["payload"])
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert not _output_directory(parent, child).exists()


def test_old_output_commit_without_delivery_plan_cannot_create_new_preparation(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "output_commit")
    shutil.rmtree(_directory(child))
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, PREPARED))
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert not _directory(child).exists()
    _assert_no_terminal(controller, parent, child)


def test_old_pending_output_without_delivery_plan_is_not_rolled_back_on_resume(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = os.link
    target = Path(parent.workspace) / "output/routes.csv"

    def linked_then_crash(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == target:
            raise SimulatedCrash("retain a legacy pending output publication")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", linked_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert (_output_directory(parent, child) / "journal.json").is_file()
    assert target.is_file()
    shutil.rmtree(_directory(child))
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, PREPARED))
    _reject_without_writes(monkeypatch, controller, parent, child, result)
    assert target.is_file()
    assert not (_output_directory(parent, child) / "rolled-back.json").exists()
    assert not _directory(child).exists()
    _assert_no_terminal(controller, parent, child)


def test_old_exact_terminal_preparation_recovers_without_creating_delivery_plan(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "terminal_prepared")
    expected = json.loads((_terminal(child) / "result.blob").read_bytes())
    assert expected["status"] == "succeeded"
    assert not _marker(child).exists()
    shutil.rmtree(_directory(child))
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, PREPARED))
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result) == expected
    assert json.loads(_marker(child).read_bytes()) == expected
    assert (_terminal(child) / "completed.json").is_file()
    assert not _directory(child).exists()
    assert _events(controller, child) == []
    _assert_count_one(child, result)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    assert _materialize(controller, parent, child, result) == expected
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_delivery_preserves_existing_output_id_and_different_parent_task_owner(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    path = Path(parent.workspace) / "output/routes.csv"
    path.parent.mkdir(parents=True)
    path.write_text("item_id,route_id\n1,A\n", encoding="utf-8")
    tasks = controller.store.list_tasks(parent.id)
    publisher = next(task for task in tasks if task.plan_task_id == "solve")
    other = next(task for task in tasks if task.id != publisher.id)
    artifact_id = controller.store.add_artifact(parent.id, other.id, "output/routes.csv", hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, "output")
    inode = path.stat().st_ino
    _interrupt(monkeypatch, controller, parent, child, result, "output_commit")
    payload = _replay_complete(monkeypatch, controller, parent, child, result)
    assert payload["outputs"][0]["artifact_id"] == artifact_id
    rows = [row for row in controller.store.list_artifacts(parent.id) if row["kind"] == "output"]
    assert len(rows) == 1 and rows[0]["task_id"] == other.id
    assert path.stat().st_ino == inode
    promotion = next(event for event in controller.store.list_events(parent.id) if event["type"] == "evolved_outputs_promoted")
    assert promotion["task_id"] == publisher.id


def test_all_optional_outputs_absent_can_resume_to_success_without_output_publication(tmp_path: Path, monkeypatch) -> None:
    raw = _contract().to_dict()
    raw["outputs"][0]["required"] = False
    contract = AlgorithmProblemContract.from_dict(raw)
    controller, parent, child, result = _fixture(tmp_path, "validation_failed", contract=contract)
    _interrupt(monkeypatch, controller, parent, child, result, "plan", contract=contract)
    payload = _replay_complete(monkeypatch, controller, parent, child, result, contract=contract)
    assert payload["status"] == "succeeded"
    assert payload["outputs"] == [] and payload["validation"]["passed"] is True
    assert not _output_directory(parent, child).exists()


@pytest.mark.parametrize("fault", ["partial_completion", "completion_directory_sync"])
def test_delivery_completion_fault_does_not_change_terminal_outcome(tmp_path: Path, monkeypatch, fault: str) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_write, original_sync = os.write, os.fsync
    writes = 0

    def write(descriptor, content):
        nonlocal writes
        if fault == "partial_completion" and _descriptor_names_path(descriptor, _directory(child) / ".completed.json.tmp"):
            writes += 1
            if writes == 1:
                return original_write(descriptor, content[:7])
            raise OSError("partial delivery completion receipt")
        return original_write(descriptor, content)

    def sync(descriptor):
        if fault == "completion_directory_sync" and (_directory(child) / "completed.json").exists() and _descriptor_names_path(descriptor, _directory(child)):
            raise OSError("delivery completion directory sync interrupted")
        return original_sync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", write)
        patch.setattr(os, "fsync", sync)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
    payload = json.loads(_marker(child).read_bytes())
    assert payload["status"] == "succeeded"
    if fault == "partial_completion":
        assert writes == 2
        _reject_without_writes(monkeypatch, controller, parent, child, result)
    else:
        assert _replay_complete(monkeypatch, controller, parent, child, result) == payload


@pytest.mark.parametrize("boundary", ["execution_committed", "plan", "output_commit", "terminal_prepared"])
def test_native_controller_exit_resumes_complete_delivery_with_one_execution(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    program = r'''
import json
import os
import sys
from pathlib import Path
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import StrategyResult
from lunar_evolution.runtime import MockRuntime
home, parent_id, child_id, raw_contract, raw_result, boundary = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
method = {"execution_committed":"commit_materialization_execution", "plan":"record_materialization_delivery", "output_commit":"commit_output_publication", "terminal_prepared":"prepare_materialization_publication"}[boundary]
original = getattr(controller.store, method)
def interrupted(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(92)
setattr(controller.store, method, interrupted)
controller.materialize_evolved_outputs(parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)), StrategyResult(**json.loads(raw_result)), timeout_seconds=1)
raise AssertionError("delivery interruption hook was not reached")
'''
    completed = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "home"), parent.id, child.id,
         json.dumps(_contract().to_dict()), json.dumps(result.to_dict()), boundary],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 92, completed.stderr
    _replay_complete(monkeypatch, controller, parent, child, result, promote=boundary in {"execution_committed", "plan"})


def test_delivery_inspection_does_not_publish_or_finish_prepared_plan(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "plan")
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    expected = json.loads((_directory(child) / "plan.json").read_bytes())
    assert delivery.inspect_materialization_delivery(controller.store, parent, child, _identity(child)) == expected
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
