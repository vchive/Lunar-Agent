"""Regression coverage for profile limits at model/tool trust boundaries."""

from copy import deepcopy
from pathlib import Path

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.memory import MemoryStore
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.tools import LocalToolRegistry
from famou.transcript import SessionTranscript


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class ScriptedModel:
    name = "fixture-model"
    api_key = None

    def __init__(self, turns: list[ModelTurn], clock: FakeClock | None = None) -> None:
        self.turns = list(turns)
        self.clock = clock
        self.elapsed_per_call = 0.0
        self.requests: list[tuple[list[dict[str, object]], tuple[dict[str, object], ...]]] = []
        self.timeouts: list[float | None] = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append((deepcopy(messages), tools))
        self.timeouts.append(timeout)
        if self.clock is not None:
            self.clock.now += self.elapsed_per_call
        return self.turns.pop(0)


def usage(total: int) -> dict[str, int]:
    return {"input_tokens": total - 1, "output_tokens": 1, "total_tokens": total}


def bounded_profile(kind: str, *, timeout: float = 5.0) -> ModelProfile:
    if kind == "tokens":
        return ModelProfile(
            "bounded", "fixture-model", timeout_seconds=timeout, max_total_tokens=10
        )
    return ModelProfile(
        "bounded", "fixture-model", timeout_seconds=timeout, max_cost_micros=10,
        input_cost_per_1k_micros=1_000, output_cost_per_1k_micros=1_000,
    )


def write_call(path: str = "forbidden.txt") -> ToolCall:
    return ToolCall(path, "write_file", {"path": path, "content": "side effect"})


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("explicit,expected", [(None, 5.0), (30.0, 5.0), (2.0, 2.0)])
def test_profile_timeout_caps_each_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
    explicit: float | None, expected: float,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr("famou.agent_loop.time.monotonic", clock.monotonic)
    model = ScriptedModel([ModelTurn("done", usage=usage(6))])
    runtime = AgentLoopRuntime(model, profile=bounded_profile("tokens"))

    getattr(runtime, mode)("solve", tmp_path, timeout=explicit)

    assert model.timeouts == [expected]


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("timeout", [0, -1, True, False, float("nan"), float("inf"), "5"])
def test_invalid_profile_timeout_fails_before_model_call(
    tmp_path: Path, mode: str, timeout: object,
) -> None:
    model = ScriptedModel([ModelTurn("done", usage=usage(6))])
    runtime = AgentLoopRuntime(model, profile=bounded_profile("tokens"))

    with pytest.raises((RuntimeExecutionError, TypeError, ValueError), match="timed out|timeout"):
        getattr(runtime, mode)("solve", tmp_path, timeout=timeout)

    assert model.requests == []


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("kind", ["tokens", "cost"])
@pytest.mark.parametrize(
    "sample", [
        None,
        {"total_tokens": 1},
        {"input_tokens": True, "output_tokens": 0, "total_tokens": 1},
        {"input_tokens": 2, "output_tokens": 1, "total_tokens": 2},
        {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3, "extra": 0},
    ],
    ids=["missing", "partial", "boolean", "inconsistent", "unknown-field"],
)
def test_bounded_profile_rejects_unaccountable_final_response(
    tmp_path: Path, mode: str, kind: str, sample: dict[str, int] | None,
) -> None:
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    transcript.append({"role": "user", "content": "prior"})
    model = ScriptedModel([ModelTurn("REJECTED_RESPONSE", usage=sample)])
    runtime = AgentLoopRuntime(
        model, profile=bounded_profile(kind), transcript=transcript,
    )

    with pytest.raises(RuntimeExecutionError, match="usage"):
        getattr(runtime, mode)("solve", tmp_path / "workspace")

    assert len(model.requests) == 1
    assert not any(item.get("content") == "REJECTED_RESPONSE" for item in transcript.load())


@pytest.mark.parametrize("kind", ["tokens", "cost"])
@pytest.mark.parametrize("sample", [None, {"total_tokens": 1}], ids=["missing", "malformed"])
def test_unaccountable_tool_turn_has_no_file_or_success_transcript(
    tmp_path: Path, kind: str, sample: dict[str, int] | None,
) -> None:
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    model = ScriptedModel([
        ModelTurn("REJECTED_RESPONSE", (write_call(),), usage=sample),
        ModelTurn("done", usage=usage(1)),
    ])
    runtime = AgentLoopRuntime(model, profile=bounded_profile(kind), transcript=transcript)
    workspace = tmp_path / "workspace"

    with pytest.raises(RuntimeExecutionError, match="usage"):
        runtime.run("solve", workspace)

    assert len(model.requests) == 1
    assert not (workspace / "forbidden.txt").exists()
    assert not any(item.get("role") in {"assistant", "tool"} for item in transcript.load())


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("with_profile", [False, True])
def test_absent_usage_remains_compatible_without_spend_ceilings(
    tmp_path: Path, mode: str, with_profile: bool,
) -> None:
    profile = ModelProfile("unbounded", "fixture-model") if with_profile else None
    model = ScriptedModel([ModelTurn("done")])

    result = getattr(AgentLoopRuntime(model, profile=profile), mode)("solve", tmp_path)

    assert result.text == "done"
    assert "total_tokens" not in result.metadata
    assert "cost_micros" not in result.metadata
    if with_profile:
        assert result.metadata["profile"] == "unbounded"


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("kind", ["tokens", "cost"])
def test_over_ceiling_final_response_is_rejected(
    tmp_path: Path, mode: str, kind: str,
) -> None:
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    model = ScriptedModel([ModelTurn("REJECTED_RESPONSE", usage=usage(11))])
    runtime = AgentLoopRuntime(model, profile=bounded_profile(kind), transcript=transcript)

    with pytest.raises(RuntimeExecutionError, match="budget"):
        getattr(runtime, mode)("solve", tmp_path / "workspace")

    assert len(model.requests) == 1
    assert not any(item.get("content") == "REJECTED_RESPONSE" for item in transcript.load())


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("kind", ["tokens", "cost"])
def test_final_response_at_exact_ceiling_succeeds_with_usage(
    tmp_path: Path, mode: str, kind: str,
) -> None:
    model = ScriptedModel([
        ModelTurn("done", response_model="fixture-model", usage=usage(10)),
    ])
    runtime = AgentLoopRuntime(model, profile=bounded_profile(kind))

    result = getattr(runtime, mode)("solve", tmp_path)

    assert result.text == "done"
    assert result.metadata["profile"] == "bounded"
    assert result.metadata["response_model"] == "fixture-model"
    assert result.metadata["total_tokens"] == "10"
    assert result.metadata["input_tokens"] == "9"
    assert result.metadata["output_tokens"] == "1"
    if kind == "cost":
        assert result.metadata["cost_micros"] == "10"


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("kind", ["tokens", "cost"])
def test_exact_ceiling_tool_response_cannot_continue_or_write(
    tmp_path: Path, mode: str, kind: str,
) -> None:
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    model = ScriptedModel([
        ModelTurn("REJECTED_RESPONSE", (write_call(),), usage=usage(10)),
        ModelTurn("done", usage=usage(1)),
    ])
    runtime = AgentLoopRuntime(model, profile=bounded_profile(kind), transcript=transcript)
    workspace = tmp_path / "workspace"

    with pytest.raises(RuntimeExecutionError):
        getattr(runtime, mode)("solve", workspace)

    assert len(model.requests) == 1
    assert not (workspace / "forbidden.txt").exists()
    assert not any(item.get("role") in {"assistant", "tool"} for item in transcript.load())


@pytest.mark.parametrize("kind", ["tokens", "cost"])
def test_normal_turns_charge_cumulatively_within_one_invocation(
    tmp_path: Path, kind: str,
) -> None:
    model = ScriptedModel([
        ModelTurn("", (write_call("allowed.txt"),), usage=usage(6)),
        ModelTurn("", (write_call(),), usage=usage(5)),
        ModelTurn("done", usage=usage(1)),
    ])
    runtime = AgentLoopRuntime(model, profile=bounded_profile(kind))

    with pytest.raises(RuntimeExecutionError, match="budget"):
        runtime.run("solve", tmp_path)

    assert len(model.requests) == 2
    assert (tmp_path / "allowed.txt").read_text() == "side effect"
    assert not (tmp_path / "forbidden.txt").exists()


def test_alternating_invocations_keep_usage_and_isolated_context_independent(tmp_path: Path) -> None:
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    transcript.append({"role": "user", "content": "HISTORY_MARKER"})
    memory = MemoryStore(tmp_path / "memory.db")
    memory.initialize()
    memory.remember("MEMORY_MARKER", scope="global")
    before_memory = memory.list()
    model = ScriptedModel([
        ModelTurn(text, response_model="fixture-model", usage=usage(6))
        for text in ("normal-one", "isolated-one", "normal-two", "isolated-two")
    ])
    runtime = AgentLoopRuntime(
        model, profile=bounded_profile("cost"), transcript=transcript,
        memory=memory, system_prompt="CUSTOM_SYSTEM_MARKER",
    )

    for index, mode in enumerate(("run", "run_isolated", "run", "run_isolated")):
        before_transcript = transcript.load()
        result = getattr(runtime, mode)(f"prompt-{index}", tmp_path / str(index))
        assert result.metadata["total_tokens"] == "6"
        assert result.metadata["cost_micros"] == "6"
        assert result.metadata["profile"] == "bounded"
        if mode == "run_isolated":
            assert transcript.load() == before_transcript
            assert result.metadata["mode"] == "agent-loop-isolated"
            assert result.metadata["session_history"] == "false"
            messages, tools = model.requests[index]
            assert [item["role"] for item in messages] == ["system", "user"]
            assert messages[-1]["content"] == f"prompt-{index}"
            assert tools == ()
            for marker in ("HISTORY_MARKER", "MEMORY_MARKER", "CUSTOM_SYSTEM_MARKER", "normal-one"):
                assert marker not in str(messages)

    assert memory.list() == before_memory


@pytest.mark.parametrize("mode", ["run", "run_isolated"])
@pytest.mark.parametrize("with_tools", [False, True])
def test_overdue_response_is_rejected_before_acceptance_or_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, with_tools: bool,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr("famou.agent_loop.time.monotonic", clock.monotonic)
    transcript = SessionTranscript(tmp_path / "session.jsonl")
    model = ScriptedModel([
        ModelTurn("REJECTED_RESPONSE", (write_call(),) if with_tools else (), usage=usage(6)),
    ], clock)
    model.elapsed_per_call = 6.0
    runtime = AgentLoopRuntime(model, profile=bounded_profile("tokens"), transcript=transcript)
    workspace = tmp_path / "workspace"

    with pytest.raises(RuntimeExecutionError, match="timed out|timeout"):
        getattr(runtime, mode)("solve", workspace)

    assert len(model.requests) == 1
    assert not (workspace / "forbidden.txt").exists()
    assert not any(item.get("role") in {"assistant", "tool"} for item in transcript.load())


def test_deadline_is_checked_immediately_before_tool_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr("famou.agent_loop.time.monotonic", clock.monotonic)
    model = ScriptedModel([ModelTurn("", (write_call(),), usage=usage(6))])
    runtime = AgentLoopRuntime(model, profile=bounded_profile("tokens"))

    def expire_on_response(event_type: str, payload: dict[str, object]) -> None:
        del payload
        if event_type == "agent_model_turn":
            clock.now = 6.0

    runtime.set_event_sink(expire_on_response)

    with pytest.raises(RuntimeExecutionError, match="timed out|timeout"):
        runtime.run("solve", tmp_path)

    assert len(model.requests) == 1
    assert not (tmp_path / "forbidden.txt").exists()


def test_deadline_after_first_tool_prevents_second_tool_and_next_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr("famou.agent_loop.time.monotonic", clock.monotonic)

    class SlowTools(LocalToolRegistry):
        def execute(self, name, arguments, workspace):
            result = super().execute(name, arguments, workspace)
            clock.now = 6.0
            return result

    model = ScriptedModel([
        ModelTurn("", (write_call("first.txt"), write_call()), usage=usage(6)),
        ModelTurn("done", usage=usage(1)),
    ])
    runtime = AgentLoopRuntime(model, tools=SlowTools(), profile=bounded_profile("tokens"))

    with pytest.raises(RuntimeExecutionError, match="timed out|timeout"):
        runtime.run("solve", tmp_path)

    assert (tmp_path / "first.txt").read_text() == "side effect"
    assert not (tmp_path / "forbidden.txt").exists()
    assert len(model.requests) == 1
