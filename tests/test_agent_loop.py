from pathlib import Path

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.memory import MemoryStore
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.tools import LocalToolRegistry


class FixtureModel:
    name = "fixture-model"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[tuple[list[dict[str, object]], tuple[dict[str, object], ...]]] = []
        self.timeouts: list[float | None] = []

    def complete(self, messages, tools=(), timeout=None):
        self.timeouts.append(timeout)
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


def test_agent_loop_aggregates_complete_provider_telemetry(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn(
                "",
                (ToolCall("1", "write_file", {"path": "solution.json", "content": "{}"}),),
                response_model="provider/model-a",
                usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            ),
            ModelTurn(
                "done",
                response_model="provider/model-a",
                usage={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
            ),
        ]
    )

    result = AgentLoopRuntime(model).run("solve", tmp_path)

    assert result.metadata["turns"] == "2"
    assert result.metadata["response_model"] == "provider/model-a"
    assert result.metadata["input_tokens"] == "30"
    assert result.metadata["output_tokens"] == "5"
    assert result.metadata["total_tokens"] == "35"


def test_agent_loop_does_not_invent_partial_provider_telemetry(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn(
                "",
                (ToolCall("1", "list_dir", {"path": "."}),),
                response_model="provider/model-a",
                usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            ),
            ModelTurn("done"),
        ]
    )

    result = AgentLoopRuntime(model).run("solve", tmp_path)

    assert "response_model" not in result.metadata
    assert "total_tokens" not in result.metadata


def test_agent_loop_enforces_model_profile_token_budget(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn(
                "",
                (ToolCall("1", "list_dir", {"path": "."}),),
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
            ModelTurn(
                "done",
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
        ]
    )
    runtime = AgentLoopRuntime(
        model,
        profile=ModelProfile("bounded", "fixture-model", max_total_tokens=10),
    )

    with pytest.raises(RuntimeExecutionError, match="model profile budget"):
        runtime.run("solve", tmp_path)
    assert len(model.requests) == 2


def test_agent_loop_profile_cost_telemetry_is_reported(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn(
                "done",
                response_model="provider/model-a",
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        ]
    )
    runtime = AgentLoopRuntime(
        model,
        profile=ModelProfile(
            "priced", "fixture-model", input_cost_per_1k_micros=1_000,
            output_cost_per_1k_micros=2_000,
        ),
    )

    result = runtime.run("solve", tmp_path)

    assert result.metadata["profile"] == "priced"
    assert result.metadata["cost_micros"] == "20"


def test_agent_loop_profile_budget_resets_for_reused_runtime(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn(
                "first",
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
            ModelTurn(
                "second",
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
        ]
    )
    runtime = AgentLoopRuntime(
        model,
        profile=ModelProfile("per-run", "fixture-model", max_total_tokens=10),
    )

    first = runtime.run("first task", tmp_path / "first")
    second = runtime.run("second task", tmp_path / "second")

    assert first.metadata["total_tokens"] == "6"
    assert second.metadata["total_tokens"] == "6"


def test_agent_loop_profile_supplies_default_timeout(tmp_path: Path) -> None:
    model = FixtureModel([ModelTurn("done")])
    runtime = AgentLoopRuntime(
        model,
        profile=ModelProfile("timed", "fixture-model", timeout_seconds=12),
    )

    runtime.run("timed task", tmp_path)

    assert model.timeouts[0] is not None
    assert 0 < model.timeouts[0] <= 12


def test_agent_loop_profile_caps_configured_step_limit(tmp_path: Path) -> None:
    model = FixtureModel(
        [
            ModelTurn("", (ToolCall("1", "list_dir", {"path": "."}),)),
            ModelTurn("", (ToolCall("2", "list_dir", {"path": "."}),)),
        ]
    )
    runtime = AgentLoopRuntime(
        model,
        max_steps=4,
        profile=ModelProfile("stepped", "fixture-model", max_steps=1),
    )

    with pytest.raises(RuntimeExecutionError, match="max steps"):
        runtime.run("step task", tmp_path)
