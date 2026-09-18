from pathlib import Path

import pytest

from famou.agent_loop import (
    AgentLoopRuntime,
    AgentLoopTimeout,
    AgentStepLimitEvidence,
    AgentStepLimitReached,
)
from famou.agents import candidate_failure_reason
from famou.memory import MemoryStore
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.tools import LocalToolRegistry
from famou.transcript import SessionTranscript


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


def test_agent_loop_rejects_over_limit_tool_batch_atomically_with_evidence(tmp_path: Path) -> None:
    model = FixtureModel([
        ModelTurn(
            "also has text, but the batch is too large",
            (
                ToolCall("1", "write_file", {"path": "first.txt", "content": "one"}),
                ToolCall("2", "write_file", {"path": "second.txt", "content": "two"}),
            ),
        ),
    ])
    events: list[tuple[str, dict[str, object]]] = []
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    runtime = AgentLoopRuntime(model, max_steps=1, transcript=transcript)
    runtime.set_event_sink(lambda event_type, payload: events.append((event_type, payload)))

    with pytest.raises(AgentStepLimitReached) as failure:
        runtime.run("save both", tmp_path)

    assert failure.value.evidence == AgentStepLimitEvidence(
        max_steps=1,
        tool_steps=0,
        attempted_tool_calls=2,
        tool_steps_remaining=1,
    )
    assert events[-1] == (
        "agent_step_limit_reached",
        {
            "max_steps": 1,
            "tool_steps": 0,
            "attempted_tool_calls": 2,
            "tool_steps_remaining": 1,
        },
    )
    assert len(model.requests) == 1
    assert not (tmp_path / "first.txt").exists()
    assert not (tmp_path / "second.txt").exists()
    assert all(message["role"] in {"system", "user"} for message in transcript.load())


def test_agent_loop_accepts_tool_free_final_when_no_steps_remain(tmp_path: Path) -> None:
    model = FixtureModel([ModelTurn("complete enough")])
    runtime = AgentLoopRuntime(model, max_steps=1)

    result = runtime.run("finish", tmp_path, tool_steps_offset=1)

    assert result.text == "complete enough"
    system = model.requests[0][0][0]["content"]
    assert '"tool_steps_remaining": 0' in system


def test_agent_loop_empty_tool_free_final_remains_a_failure(tmp_path: Path) -> None:
    model = FixtureModel([ModelTurn("")])

    with pytest.raises(RuntimeExecutionError, match="without a final text result"):
        AgentLoopRuntime(model).run("finish", tmp_path)


def test_candidate_local_timeout_is_typed_as_timed_out(tmp_path: Path) -> None:
    model = FixtureModel([ModelTurn("complete candidate")])
    runtime = AgentLoopRuntime(model)

    with pytest.raises(AgentLoopTimeout):
        runtime._remaining_timeout(0.0, 0.0)

    assert candidate_failure_reason(AgentLoopTimeout("deadline")) == "timeout"


def test_candidate_local_timeout_updates_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = FixtureModel([ModelTurn("complete candidate")])
    runtime = AgentLoopRuntime(model)
    clock = iter((1.0, 2.0))
    monkeypatch.setattr("famou.agent_loop.time.monotonic", lambda: next(clock))

    with pytest.raises(AgentLoopTimeout):
        runtime.run(
            "finish", tmp_path, timeout=0.01,
            max_tool_steps=2, budget_id="candidate-timeout",
        )

    diagnostic = runtime.last_candidate_diagnostic
    assert diagnostic is not None
    assert diagnostic["outcome"] == "timed_out"
    assert diagnostic["reason"] == "timeout"
    assert diagnostic["phase"] == "model_turn"
    assert diagnostic["completion"] is False


def test_agent_loop_reports_candidate_budget_completion(tmp_path: Path) -> None:
    model = FixtureModel([ModelTurn("complete candidate")])
    runtime = AgentLoopRuntime(model, max_steps=40)

    result = runtime.run(
        "finish", tmp_path, max_tool_steps=4, budget_id="candidate-00000000-0001",
    )

    assert result.metadata["candidate_budget_id"] == "candidate-00000000-0001"
    assert result.metadata["candidate_completion"] == "true"
    assert result.metadata["candidate_reason"] == "completed"
    assert result.metadata["candidate_tool_steps_remaining"] == "4"


def test_agent_loop_reports_candidate_budget_limit(tmp_path: Path) -> None:
    model = FixtureModel([
        ModelTurn("", (
            ToolCall("1", "list_dir", {"path": "."}),
            ToolCall("2", "list_dir", {"path": "."}),
        )),
    ])
    runtime = AgentLoopRuntime(model, max_steps=40)

    with pytest.raises(AgentStepLimitReached):
        runtime.run("finish", tmp_path, max_tool_steps=1, budget_id="candidate-1")

    diagnostic = runtime.last_candidate_diagnostic
    assert diagnostic is not None
    assert diagnostic["budget_id"] == "candidate-1"
    assert diagnostic["max_tool_steps"] == 1
    assert diagnostic["tool_steps_used"] == 0
    assert diagnostic["tool_steps_remaining"] == 1
    assert diagnostic["attempted_tool_calls"] == 2
    assert diagnostic["completion"] is False
    assert diagnostic["reason"] == "tool_step_limit_reached"
    assert diagnostic["phase"] == "tool_batch"
    assert diagnostic["schema_version"] == "1"
    assert diagnostic["stage"] == "candidate_generation"
    assert diagnostic["outcome"] == "tool_step_limit_reached"


def test_candidate_budget_is_independent_of_runtime_default_max_steps(tmp_path: Path) -> None:
    model = FixtureModel([
        ModelTurn("", (ToolCall("1", "list_dir", {"path": "."}),)),
        ModelTurn("", (ToolCall("2", "list_dir", {"path": "."}),)),
        ModelTurn("complete candidate"),
    ])
    runtime = AgentLoopRuntime(model, max_steps=1)

    result = runtime.run(
        "finish", tmp_path, max_tool_steps=2, budget_id="candidate-independent",
    )

    assert result.text == "complete candidate"
    assert runtime.last_tool_steps == 2
    assert runtime.last_candidate_diagnostic is not None
    assert runtime.last_candidate_diagnostic["max_tool_steps"] == 2


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
