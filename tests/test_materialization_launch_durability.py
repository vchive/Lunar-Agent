"""Durability faults distinguish unused staging from a non-replayable launch intent."""

import os
from pathlib import Path

import pytest
from test_materialization_launch import (
    _assert_no_terminal_claim,
    _attempt,
    _database_snapshot,
    _deny_runner,
    _events,
    _filesystem_snapshot,
    _fixture,
    _intent,
    _materialize,
)

from famou.evolution import CommandCandidateRunner
from famou.materialization_launch import MaterializationLaunchUncertain


def _descriptor_names_path(descriptor: int, path: Path) -> bool:
    try:
        expected = path.stat()
    except FileNotFoundError:
        return False
    held = os.fstat(descriptor)
    return (held.st_dev, held.st_ino) == (expected.st_dev, expected.st_ino)


def _assert_retained_intent_never_relaunches(monkeypatch, controller, parent, child, result) -> None:
    attempt = _attempt(child, result)
    (attempt / "preserve-durability-failure.txt").write_text("retained attempt", encoding="utf-8")
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)
    for _ in range(2):
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger
        assert not (attempt / "execution-count.txt").exists()
        assert not (attempt / "execution.json").exists()
        assert not (attempt / ".execution.json.tmp").exists()
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("fault", ["source_file", "source_directory"])
def test_source_sync_failure_before_intent_allows_one_safe_later_attempt(
    tmp_path: Path, monkeypatch, fault: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    attempt = _attempt(child, result)
    target = attempt / "candidate.py" if fault == "source_file" else attempt
    original_sync = os.fsync
    injected = 0

    def sync(descriptor):
        nonlocal injected
        if _descriptor_names_path(descriptor, target):
            injected += 1
            raise OSError("fixture source durability failure")
        return original_sync(descriptor)

    with monkeypatch.context() as patch:
        _deny_runner(patch)
        patch.setattr(os, "fsync", sync)
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
    assert injected == 1
    assert not _intent(child).exists()
    assert not _intent(child).with_name(".launch-intent.json.tmp").exists()
    assert _events(controller, child) == []
    assert not (attempt / "execution-count.txt").exists()
    _assert_no_terminal_claim(controller, parent, child)
    disposable = attempt / "unused-preexecution-staging.txt"
    disposable.write_text("safe to replace before the first launch", encoding="utf-8")
    original_run = CommandCandidateRunner.run
    calls = 0

    def run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(CommandCandidateRunner, "run", run)
    materialized = _materialize(controller, parent, child, result)
    assert materialized["status"] == "succeeded"
    assert not disposable.exists()
    assert calls == 1
    assert (attempt / "execution-count.txt").read_text() == "1"
    assert _materialize(controller, parent, child, result) == materialized
    assert calls == 1


@pytest.mark.parametrize("fault", [
    "partial_write", "zero_progress", "temporary_directory_sync", "intent_file_sync", "linked_directory_sync",
])
def test_intent_write_and_sync_failures_preserve_uncertainty_without_cleanup(
    tmp_path: Path, monkeypatch, fault: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    final = _intent(child)
    temporary = final.with_name(".launch-intent.json.tmp")
    original_write, original_sync = os.write, os.fsync
    writes = 0
    injected = 0

    def write(descriptor, content):
        nonlocal writes, injected
        if _descriptor_names_path(descriptor, temporary):
            writes += 1
            if fault == "zero_progress":
                injected += 1
                return 0
            if fault == "partial_write":
                if writes == 1:
                    return original_write(descriptor, content[:11])
                injected += 1
                raise OSError("fixture stopped after partial intent write")
        return original_write(descriptor, content)

    def sync(descriptor):
        nonlocal injected
        should_fail = (
            fault == "intent_file_sync" and _descriptor_names_path(descriptor, temporary)
        ) or (
            fault == "temporary_directory_sync" and temporary.exists() and not final.exists()
            and _descriptor_names_path(descriptor, final.parent)
        ) or (
            fault == "linked_directory_sync" and final.exists()
            and _descriptor_names_path(descriptor, final.parent)
        )
        if should_fail:
            injected += 1
            raise OSError("fixture intent durability failure")
        return original_sync(descriptor)

    with monkeypatch.context() as patch:
        _deny_runner(patch)
        patch.setattr(os, "write", write)
        patch.setattr(os, "fsync", sync)
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
    assert injected == 1
    assert final.exists() is (fault == "linked_directory_sync")
    assert temporary.exists() is (fault != "linked_directory_sync")
    if fault == "partial_write":
        assert temporary.stat().st_size == 11 and writes == 2
    elif fault in {"zero_progress", "temporary_directory_sync"}:
        assert temporary.stat().st_size == 0
    elif fault == "intent_file_sync":
        assert temporary.stat().st_size > 11
    assert _events(controller, child) == []
    _assert_no_terminal_claim(controller, parent, child)
    _assert_retained_intent_never_relaunches(monkeypatch, controller, parent, child, result)


def test_postcommit_exception_allows_only_the_current_caller_after_exact_readback(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_record = controller.store.record_materialization_launch_intent
    original_probe = controller.store.materialization_launch_intent_recorded
    original_run = CommandCandidateRunner.run
    records = 0
    confirmed = 0
    calls = 0

    def record_then_raise(*args, **kwargs):
        nonlocal records
        records += 1
        original_record(*args, **kwargs)
        raise RuntimeError("fixture exception after exact SQLite commit")

    def probe(*args, **kwargs):
        nonlocal confirmed
        value = original_probe(*args, **kwargs)
        if value:
            confirmed += 1
        return value

    def run(*args, **kwargs):
        nonlocal calls
        assert confirmed >= 1
        assert len(_events(controller, child)) == 1
        calls += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(controller.store, "record_materialization_launch_intent", record_then_raise)
    monkeypatch.setattr(controller.store, "materialization_launch_intent_recorded", probe)
    monkeypatch.setattr(CommandCandidateRunner, "run", run)
    materialized = _materialize(controller, parent, child, result)
    assert materialized["status"] == "succeeded"
    assert records == calls == 1
    assert confirmed >= 1
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)
    for _ in range(2):
        assert _materialize(controller, parent, child, result) == materialized
        assert _database_snapshot(controller, parent, child) == ledger
    assert records == calls == 1


@pytest.mark.parametrize("committed", [False, True], ids=["before_commit", "after_commit"])
def test_unqueryable_commit_never_grants_a_later_launch(
    tmp_path: Path, monkeypatch, committed: bool,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_record = controller.store.record_materialization_launch_intent
    records = 0
    queries = 0

    def record_uncertain(*args, **kwargs):
        nonlocal records
        records += 1
        if committed:
            original_record(*args, **kwargs)
        raise OSError("fixture unconfirmed commit return")

    def unavailable_probe(*args, **kwargs):
        nonlocal queries
        queries += 1
        raise OSError("fixture exact commit probe unavailable")

    with monkeypatch.context() as patch:
        _deny_runner(patch)
        patch.setattr(controller.store, "record_materialization_launch_intent", record_uncertain)
        patch.setattr(controller.store, "materialization_launch_intent_recorded", unavailable_probe)
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
    assert records == queries == 1
    assert _intent(child).is_file()
    assert not _intent(child).with_name(".launch-intent.json.tmp").exists()
    assert len(_events(controller, child)) == int(committed)
    _assert_no_terminal_claim(controller, parent, child)
    _assert_retained_intent_never_relaunches(monkeypatch, controller, parent, child, result)
