from pathlib import Path

from famou.agent_loop import AgentLoopRuntime
from famou.config import Config
from famou.controller import LocalController
from famou.memory import MemoryStore
from famou.runtime import MockRuntime, ModelTurn, ToolCall
from famou.tools import LocalToolRegistry


class FixtureModel:
    name = "fixture"

    def __init__(self) -> None:
        self.turns = [
            ModelTurn("", (ToolCall("1", "write_file", {"path": "output.txt", "content": "ok"}),)),
            ModelTurn("done", ()),
        ]

    def complete(self, messages, tools=(), timeout=None):
        del messages, tools, timeout
        return self.turns.pop(0)

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


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


def test_controller_wires_hermes_loop_events_and_artifacts(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    memory = MemoryStore(config.database)
    runtime = AgentLoopRuntime(
        FixtureModel(),
        tools=LocalToolRegistry(),
        max_steps=3,
    )
    controller = LocalController(config, runtime, memory=memory)
    run = controller.start("write a file")

    assert run.status.value == "succeeded"
    artifacts = controller.store.list_artifacts(run.id)
    assert any(item["path"].endswith("output.txt") for item in artifacts)
    event_types = [item["type"] for item in controller.store.list_events(run.id)]
    assert "agent_model_turn" in event_types
    assert "agent_tool_result" in event_types
