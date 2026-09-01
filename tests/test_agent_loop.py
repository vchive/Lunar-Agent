from pathlib import Path

from famou.agent_loop import AgentLoopRuntime
from famou.memory import MemoryStore
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.tools import LocalToolRegistry


class FixtureModel:
    name = "fixture-model"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[tuple[list[dict[str, object]], tuple[dict[str, object], ...]]] = []

    def complete(self, messages, tools=(), timeout=None):
        del timeout
        self.requests.append((messages, tools))
        return self.turns.pop(0)

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_hermes_loop_executes_tools_and_memory_explicitly(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    memory.remember("private note that must be explicitly recalled", scope="global")
    model = FixtureModel(
        [
            ModelTurn(
                "",
                (
                    ToolCall("1", "write_file", {"path": "answer.txt", "content": "done"}),
                    ToolCall("2", "remember_memory", {"content": "The answer is done", "kind": "fact"}),
                ),
            ),
            ModelTurn("Finished and saved answer.txt", ()),
        ]
    )
    events: list[tuple[str, dict[str, object]]] = []
    runtime = AgentLoopRuntime(
        model,
        tools=LocalToolRegistry(memory=memory),
        memory=memory,
        max_steps=3,
    )
    runtime.set_context("run-1", "task-1")
    runtime.set_event_sink(lambda event_type, payload: events.append((event_type, payload)))

    result = runtime.run("create an answer", tmp_path / "workspace")

    assert result.text == "Finished and saved answer.txt"
    assert result.artifacts == ("answer.txt",)
    assert (tmp_path / "workspace" / "answer.txt").read_text() == "done"
    assert memory.recall("answer", scopes=("run:run-1",))[0].content == "The answer is done"
    assert all(
        "private note" not in str(message.get("content", ""))
        for message in model.requests[0][0]
    )
    assert [kind for kind, _ in events] == [
        "agent_model_turn",
        "agent_tool_result",
        "agent_tool_result",
        "agent_model_turn",
    ]
    assert any(
        call["function"]["name"] == "remember_memory" for call in model.requests[0][1]
    )
    second_messages = model.requests[1][0]
    assert second_messages[-3]["role"] == "assistant"
    assert second_messages[-2]["role"] == "tool"
    assert second_messages[-1]["role"] == "tool"
    assert "answer.txt" in str(second_messages[-2]["content"])


def test_memory_tools_are_not_available_without_opt_in(tmp_path: Path) -> None:
    registry = LocalToolRegistry()
    assert all(
        item["function"]["name"] not in {"remember_memory", "recall_memory"}
        for item in registry.schemas()
    )
    result = registry.execute("recall_memory", {"query": "secret"}, tmp_path)
    assert not result.success


def test_memory_tool_redacts_configured_api_key(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    registry = LocalToolRegistry(memory=memory, redactions=("api-secret",))
    result = registry.execute(
        "remember_memory",
        {"content": "endpoint uses api-secret", "kind": "note"},
        tmp_path,
    )
    assert result.success
    assert memory.list()[0].content == "endpoint uses [REDACTED]"


def test_agent_loop_step_limit_is_a_runtime_failure(tmp_path: Path) -> None:
    model = FixtureModel(
        [ModelTurn("", (ToolCall("1", "list_dir", {"path": "."}),))]
    )
    runtime = AgentLoopRuntime(model, max_steps=1)
    model.turns.append(ModelTurn("", (ToolCall("2", "list_dir", {"path": "."}),)))
    try:
        runtime.run("loop", tmp_path)
    except RuntimeExecutionError as exc:
        assert "max steps" in str(exc)
    else:
        raise AssertionError("step limit should fail the runtime")
