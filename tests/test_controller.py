from pathlib import Path

from famou.config import Config
from famou.controller import LocalController
from famou.runtime import MockRuntime


def test_controller_completes_mock_run_and_is_idempotent(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.start("produce a local report")
    assert run.status.value == "succeeded"
    artifacts = controller.store.list_artifacts(run.id)
    assert len(artifacts) == 2  # prompt and result are independently inspectable
    assert all((run.workspace / item["path"]).is_file() for item in artifacts)

    resumed = controller.resume(run.id)
    assert resumed.status == run.status
    assert len(controller.store.list_artifacts(run.id)) == 2
    assert sum(event["type"] == "run_succeeded" for event in controller.store.list_events(run.id)) == 1


def test_controller_recovers_a_claimed_task(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.store.create_run("recover me")
    task = controller.store.next_task(run.id)
    assert task is not None
    assert controller.store.claim_task(task.id, "mock") is not None
    resumed = controller.resume(run.id)
    assert resumed.status.value == "succeeded"
