"""Offline contract tests for the public parent/preparation status projection."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from famou import cli
from famou.config import Config
from famou.models import Run, RunStatus
from famou.store import Store


def run(status: RunStatus) -> Run:
    return Run(
        id="parent",
        goal="goal",
        status=status,
        workspace=Path("/tmp/lunar-status-projection"),
        created_at="2026-09-19T00:00:00Z",
        updated_at="2026-09-19T00:00:00Z",
    )


def test_recoverable_preparation_exposes_failed_effective_status_without_rewriting_parent():
    projection = cli._status_projection(
        run(RunStatus.RUNNING),
        preparation={
            "status": "failed",
            "error_category": "runtime_error",
            "recoverable": True,
        },
    )
    assert projection == {
        "status": "failed",
        "run_status": "running",
        "preparation_status": "failed",
        "preparation_recoverable": True,
        "reason_code": "preparation_runtime_error",
    }


def test_timeout_unknown_and_cancelled_preparation_reasons_are_bounded():
    timeout = cli._status_projection(
        run(RunStatus.RUNNING),
        preparation={"status": "failed", "error_category": "preparation_timeout", "recoverable": True},
    )
    unknown = cli._status_projection(
        run(RunStatus.RUNNING),
        preparation={"status": "unknown", "error_category": "private-provider-detail", "recoverable": False},
    )
    cancelled = cli._status_projection(
        run(RunStatus.CANCELLED),
        preparation={"status": "failed", "error_category": "cancelled", "recoverable": False},
    )
    assert timeout["reason_code"] == "preparation_timeout"
    assert unknown["reason_code"] == "preparation_unknown"
    assert cancelled["status"] == "cancelled" and cancelled["reason_code"] == "cancelled"
    assert "private-provider-detail" not in str(unknown)


def test_terminal_parent_wins_over_preparation_and_prepared_child_does_not_finish_parent():
    terminal = cli._status_projection(
        run(RunStatus.SUCCEEDED),
        preparation={"status": "failed", "error_category": "runtime_error", "recoverable": True},
    )
    child_finished = cli._status_projection(
        run(RunStatus.RUNNING),
        preparation={"status": "prepared", "recoverable": False},
        evolution_status="succeeded",
    )
    assert terminal["status"] == "succeeded" and terminal["reason_code"] == "terminal_succeeded"
    assert child_finished["status"] == "running" and child_finished["reason_code"] == "run_running"


def test_status_payload_has_stable_projection_fields_and_is_read_only(tmp_path):
    config = Config(tmp_path / "home")
    config.ensure()
    store = Store(config.database)
    store.initialize()
    parent = store.create_run("goal", workspace=config.workspace_for("parent"))
    before = store.list_events(parent.id), store.list_artifacts(parent.id)
    payload = cli._status_payload(config, parent.id)
    assert payload is not None
    assert payload["status"] == "pending"
    assert payload["run_status"] == "pending"
    assert payload["preparation_status"] is None
    assert payload["preparation_recoverable"] is False
    assert payload["reason_code"] == "run_pending"
    assert (store.list_events(parent.id), store.list_artifacts(parent.id)) == before


@pytest.mark.parametrize("failure", ["evolution", "materialization"])
def test_text_status_json_and_solve_agree_on_delivery_failure(tmp_path, capsys, failure):
    config = Config(tmp_path / "home")
    config.ensure()
    store = Store(config.database)
    store.initialize()
    parent = store.create_run("goal", workspace=config.workspace_for("parent"))
    child = store.create_run("evolution", workspace=config.workspace_for("child"))
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (RunStatus.SUCCEEDED.value, parent.id))
        connection.execute(
            "UPDATE runs SET status = ? WHERE id = ?",
            (RunStatus.FAILED.value if failure == "evolution" else RunStatus.SUCCEEDED.value, child.id),
        )
    store.append_event(parent.id, "evolution_linked", {"evolution_run_id": child.id})
    if failure == "materialization":
        store.append_event(parent.id, "bundle_candidate_delivered", {"status": "failed"})
    before = store.get_run(parent.id), store.list_events(parent.id), store.list_artifacts(parent.id)
    status = cli._status_payload(config, parent.id)
    solved = cli._solve_payload(SimpleNamespace(store=store), store.get_run(parent.id))
    assert status["status"] == solved["status"] == "failed"
    assert status["run_status"] == solved["run_status"] == "succeeded"
    assert status["reason_code"] == solved["reason_code"] == f"{failure}_failed"
    assert cli._print_status(config, parent.id) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "status: failed" in lines
    assert "run_status: succeeded" in lines
    assert f"status_reason: {failure}_failed" in lines
    assert (store.get_run(parent.id), store.list_events(parent.id), store.list_artifacts(parent.id)) == before
