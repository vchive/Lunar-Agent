from pathlib import Path

from famou.models import TaskStatus
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
