import json
import sqlite3
from pathlib import Path

from famou.models import TaskStatus
from famou.policy import PlanDocument, PlanTask
from famou.store import Store


def test_running_task_is_recovered_and_events_are_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("recover this goal", tmp_path / "runs" / "run")
    task = store.next_task(run.id)
    assert task is not None
    attempt = store.claim_task(task.id, "mock")
    assert attempt is not None
    assert store.recover_running(run.id) == 1
    assert store.get_task(task.id).state == TaskStatus.UNCERTAIN  # type: ignore[union-attr]

    assert store.append_event(run.id, "probe", {"ok": True}, event_id="same-event")
    assert not store.append_event(run.id, "probe", {"ok": True}, event_id="same-event")
    assert sum(event["id"] == "same-event" for event in store.list_events(run.id)) == 1


def test_feature006_migrates_initial_plan_revision_key(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
            workspace TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE plan_revisions (
            plan_id TEXT NOT NULL, run_id TEXT NOT NULL, version INTEGER NOT NULL,
            parent_version INTEGER, document TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(plan_id, version)
        );
        CREATE INDEX plan_revisions_run_idx ON plan_revisions(run_id, version);
        """
    )
    connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("r", "g", "pending", "w", "t", "t"))
    document = PlanDocument(goal="legacy", plan_id="plan-legacy", tasks=(PlanTask("one", "One", "one"),))
    connection.execute(
        "INSERT INTO plan_revisions VALUES (?, ?, ?, ?, ?, ?)",
        (document.plan_id, "r", 1, None, json.dumps(document.to_dict()), "t"),
    )
    connection.commit()
    connection.close()

    Store(database).initialize()
    check = sqlite3.connect(database)
    primary = [row[1] for row in check.execute("PRAGMA table_info(plan_revisions)") if row[5]]
    assert primary == ["run_id", "version"]
    assert check.execute("SELECT COUNT(*) FROM plan_revisions").fetchone()[0] == 1
    check.close()
