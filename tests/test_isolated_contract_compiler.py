"""Offline protocol tests using the real Hermes runtime and deterministic model turns."""

import json
import sys
from pathlib import Path

import pytest

from lunar_evolution.agent_loop import (
    ISOLATED_SYSTEM_PROMPT,
    AgentLoopRuntime,
    ProfileBudgetFailure,
)
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.conversational import ContractCompilationError, RuntimeContractCompiler
from lunar_evolution.memory import MemoryStore
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.runtime import (
    MockRuntime,
    ModelTurn,
    RuntimeResult,
    SubprocessRuntime,
    ToolCall,
)
from lunar_evolution.transcript import SessionTranscript


def _contract() -> dict[str, object]:
    return {
        "schema_version": "1",
        "problem_id": "isolated-routing",
        "problem_type": "routing",
        "statement": "Route all orders.",
        "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order id"}}],
        "decision_variables": ["route order"],
        "objective": {"name": "distance", "direction": "minimize"},
        "hard_constraints": [],
        "soft_constraints": [],
        "success_criteria": ["Every order is served."],
        "deliverables": ["Route table."],
    }


def _compiled(contract: dict[str, object] | None = None) -> str:
    return json.dumps({"status": "compiled", "contract": contract or _contract()})


NEEDS_INPUT = json.dumps({
    "status": "needs_input",
    "questions": [{"question": "What are the input fields?", "options": []}],
    "evidence": ["The goal does not specify an input schema."],
})


class RecordingModel:
    name = "offline-contract-model"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[tuple[list[dict[str, object]], tuple[dict[str, object], ...]]] = []
        self.timeouts: list[float | None] = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append((json.loads(json.dumps(messages)), tools))
        self.timeouts.append(timeout)
        return self.turns.pop(0)

    def cancel(self) -> None:
        pass

    def process_info(self) -> tuple[None, None]:
        return None, None

    def set_process_observer(self, observer) -> None:
        pass


def test_compiler_uses_only_goal_answer_and_isolated_system_without_tools(tmp_path: Path) -> None:
    transcript = SessionTranscript(tmp_path / "prior-session.jsonl")
    transcript.append({"role": "user", "content": "PRIOR_SESSION_MARKER"})
    transcript.append({"role": "assistant", "content": "PRIOR_COMPILER_MARKER"})
    transcript_before = transcript.path.read_bytes()
    memory = MemoryStore(tmp_path / "memory.db")
    memory.initialize()
    memory.remember("PRIVATE_MEMORY_MARKER", scope="global")
    memory_before = memory.list()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "private.txt").write_text("PRIVATE_FILE_MARKER", encoding="utf-8")
    model = RecordingModel([ModelTurn(_compiled())])
    runtime = AgentLoopRuntime(
        model, memory=memory, transcript=transcript, session_history=True,
        system_prompt="CUSTOM_SYSTEM_MARKER",
    )
    goal = "Route orders from orders.csv; minimize distance and deliver a route table."
    answer = "The CSV has one field named id, the order identifier."

    result = RuntimeContractCompiler(runtime).compile(
        goal, workspace, answer=answer, timeout=7.25,
    )

    assert result.status == "compiled"
    assert result.contract is not None
    assert result.contract.inputs[0].fields == {"id": "order id"}
    assert len(model.requests) == 1
    messages, tools = model.requests[0]
    assert messages[0] == {"role": "system", "content": ISOLATED_SYSTEM_PROMPT}
    assert [message["role"] for message in messages] == ["system", "user"]
    assert tools == ()
    assert goal in messages[1]["content"]
    assert answer in messages[1]["content"]
    assert model.timeouts == [7.25]
    for marker in (
        "PRIOR_SESSION_MARKER", "PRIOR_COMPILER_MARKER", "PRIVATE_MEMORY_MARKER",
        "PRIVATE_FILE_MARKER", "CUSTOM_SYSTEM_MARKER", "files changed and checks performed",
    ):
        assert marker not in json.dumps(model.requests)
    assert transcript.path.read_bytes() == transcript_before
    assert memory.list() == memory_before
    assert list(workspace.iterdir()) == [workspace / "private.txt"]


def test_compiler_prompt_declares_evolution_types_bounds_and_defaults() -> None:
    prompt = RuntimeContractCompiler._prompt("Route orders", None)
    for instruction in (
        "only strategy, max_rounds, stagnation_rounds",
        '"population" (default) or "openevolve"',
        'never emit the retired "loop"',
        "max_rounds is an integer from 1 to 10000 (default 5)",
        "stagnation_rounds is an integer from 1 to 1000 (default 3)",
        "must not be booleans, strings, or decimals",
        "Omit evolution or unspecified settings to retain their defaults",
        "Do not add population_size, offspring_per_iteration",
        "object mapping field-name strings to description strings",
        "fields (array of unique field-name strings, not an object",
        "JSON boolean, default true",
    ):
        assert instruction in prompt


@pytest.mark.parametrize("evolution, expected", [
    (None, {"strategy": "population", "max_rounds": 5, "stagnation_rounds": 3}),
    ({}, {"strategy": "population", "max_rounds": 5, "stagnation_rounds": 3}),
    ({"strategy": "openevolve"}, {
        "strategy": "openevolve", "max_rounds": 5, "stagnation_rounds": 3,
    }),
    ({"max_rounds": 1, "stagnation_rounds": 1}, {
        "strategy": "population", "max_rounds": 1, "stagnation_rounds": 1,
    }),
    ({"max_rounds": 10000, "stagnation_rounds": 1000}, {
        "strategy": "population", "max_rounds": 10000, "stagnation_rounds": 1000,
    }),
])
def test_evolution_optional_settings_and_boundaries_still_parse(
    tmp_path: Path, evolution, expected,
) -> None:
    contract = _contract()
    if evolution is not None:
        contract["evolution"] = evolution
    model = RecordingModel([ModelTurn(_compiled(contract))])

    result = RuntimeContractCompiler(AgentLoopRuntime(model)).compile("Route orders", tmp_path)

    assert result.contract is not None
    assert result.contract.evolution.to_dict() == expected
    assert len(model.requests) == 1


@pytest.mark.parametrize("evolution", [
    {"population_size": 8},
    {"strategy": "loop"},
    {"max_rounds": 0},
    {"max_rounds": 10001},
    {"max_rounds": True},
    {"max_rounds": "5"},
    {"max_rounds": 5.0},
    {"stagnation_rounds": 0},
    {"stagnation_rounds": 1001},
])
def test_invalid_evolution_is_rejected_once_without_repair(tmp_path: Path, evolution) -> None:
    model = RecordingModel([ModelTurn(_compiled({**_contract(), "evolution": evolution}))])

    with pytest.raises(ContractCompilationError):
        RuntimeContractCompiler(AgentLoopRuntime(model)).compile("Route orders", tmp_path)

    assert len(model.requests) == 1
    assert model.requests[0][1] == ()


@pytest.mark.parametrize("text", [
    "Here is the contract:\n```json\n" + _compiled() + "\n```",
    _compiled() + "\nFinished compiling the contract.",
    '{"status":"compiled","contract":',
])
def test_non_json_response_stays_a_single_failure(tmp_path: Path, text: str) -> None:
    model = RecordingModel([ModelTurn(text)])

    with pytest.raises(ContractCompilationError, match="one strict JSON object"):
        RuntimeContractCompiler(AgentLoopRuntime(model)).compile("Route orders", tmp_path)

    assert len(model.requests) == 1
    assert not list(tmp_path.iterdir())


def test_isolated_tool_call_fails_without_executing_or_retrying(tmp_path: Path) -> None:
    model = RecordingModel([ModelTurn(_compiled(), (
        ToolCall("1", "write_file", {"path": "unexpected.txt", "content": "unexpected"}),
    ))])

    with pytest.raises(ContractCompilationError, match="isolated agent turn returned tool calls"):
        RuntimeContractCompiler(AgentLoopRuntime(model)).compile("Route orders", tmp_path)

    assert len(model.requests) == 1
    assert not (tmp_path / "unexpected.txt").exists()


def test_isolated_runtime_exception_does_not_fall_back(tmp_path: Path) -> None:
    class FailingRuntime:
        name = "isolated-failure"
        isolated_calls = 0
        regular_calls = 0

        def run_isolated(self, prompt, workspace, timeout=None):
            self.isolated_calls += 1
            raise TimeoutError("offline timeout")

        def run(self, prompt, workspace, timeout=None):
            self.regular_calls += 1
            return RuntimeResult(_compiled())

    runtime = FailingRuntime()

    with pytest.raises(ContractCompilationError, match="TimeoutError: offline timeout"):
        RuntimeContractCompiler(runtime).compile("Route orders", tmp_path)

    assert runtime.isolated_calls == 1
    assert runtime.regular_calls == 0


@pytest.mark.parametrize("total_tokens", [10, 11])
def test_isolated_compiler_preserves_profile_timeout_and_usage_limits(
    tmp_path: Path, total_tokens: int,
) -> None:
    model = RecordingModel([ModelTurn(
        _compiled(), response_model="reported-fixture",
        usage={"input_tokens": 4, "output_tokens": total_tokens - 4, "total_tokens": total_tokens},
    )])
    profile = ModelProfile(
        name="offline", model="requested-fixture", timeout_seconds=3, max_total_tokens=10,
    )
    compiler = RuntimeContractCompiler(AgentLoopRuntime(model, profile=profile))

    if total_tokens == 10:
        assert compiler.compile("Route orders", tmp_path, timeout=20).status == "compiled"
    else:
        with pytest.raises(ContractCompilationError, match="max_total_tokens") as caught:
            compiler.compile("Route orders", tmp_path, timeout=20)
        failure = caught.value.__cause__
        assert isinstance(failure, ProfileBudgetFailure)
        assert failure.evidence.observed_usage.total_tokens == 11
        assert failure.evidence.accepted_usage.total_tokens == 0
    assert len(model.requests) == 1
    assert 0 < model.timeouts[0] <= 3
    assert model.requests[0][1] == ()


def test_compiler_falls_back_when_isolated_entry_is_not_callable(tmp_path: Path) -> None:
    class LegacyRuntime:
        name = "legacy"
        run_isolated = None

        def __init__(self):
            self.calls = []

        def run(self, prompt, workspace, timeout=None):
            self.calls.append((prompt, workspace, timeout))
            return RuntimeResult(NEEDS_INPUT)

    runtime = LegacyRuntime()
    result = RuntimeContractCompiler(runtime).compile("Route orders", tmp_path, timeout=2)

    assert result.status == "needs_input"
    assert len(runtime.calls) == 1
    assert runtime.calls[0][1:] == (tmp_path, 2)


def test_subprocess_compiler_without_isolated_entry_still_receives_prompt(tmp_path: Path) -> None:
    source = (
        "import pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "assert 'Route orders' in prompt and 'User-supplied schema' in prompt\n"
        "pathlib.Path('invocations.txt').write_text('one')\n"
        f"print({NEEDS_INPUT!r})\n"
    )
    runtime = SubprocessRuntime((str(Path(sys.executable).resolve()), "-c", source))

    result = RuntimeContractCompiler(runtime).compile(
        "Route orders", tmp_path, answer="User-supplied schema", timeout=10,
    )

    assert result.status == "needs_input"
    assert result.questions[0].question == "What are the input fields?"
    assert (tmp_path / "invocations.txt").read_text() == "one"


def test_normal_solving_after_contract_compile_keeps_hermes_tools(tmp_path: Path) -> None:
    model = RecordingModel([
        ModelTurn(_compiled()),
        ModelTurn("", (ToolCall("1", "write_file", {"path": "answer.txt", "content": "done"}),)),
        ModelTurn("Finished and saved answer.txt"),
    ])
    runtime = AgentLoopRuntime(model)

    assert RuntimeContractCompiler(runtime).compile("Route orders", tmp_path).status == "compiled"
    result = runtime.run("Write the answer", tmp_path)

    assert result.text == "Finished and saved answer.txt"
    assert (tmp_path / "answer.txt").read_text() == "done"
    assert model.requests[0][1] == ()
    assert "files changed and checks performed" in model.requests[1][0][0]["content"]
    assert any(tool["function"]["name"] == "write_file" for tool in model.requests[1][1])
    assert model.requests[2][0][-1]["role"] == "tool"


def test_needs_input_answer_resume_compiles_same_run_once(tmp_path: Path) -> None:
    model = RecordingModel([ModelTurn(NEEDS_INPUT), ModelTurn(_compiled())])
    runtime = AgentLoopRuntime(model)
    compiler = RuntimeContractCompiler(runtime)
    controller = LocalController(Config(tmp_path / "home"), runtime)
    run = controller.start_conversational(
        "Route orders", compiler, compiler_fingerprint="unchanged-fixture", execute_plan=False,
    )
    assert run.status.value == "awaiting_input"
    assert run.current_plan_id is None
    pending = controller.store.pending_input(run.id)
    assert pending is not None
    answer = "orders.csv contains id; minimize distance and deliver a route table."
    answer_path = run.workspace / "tasks" / pending["task_id"] / "input-answer.json"
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(json.dumps({"answer": answer}), encoding="utf-8")
    relative = answer_path.relative_to(run.workspace).as_posix()
    controller.store.add_artifact(
        run.id, pending["task_id"], relative, "0" * 64, answer_path.stat().st_size, "input",
    )
    controller.store.answer_input(run.id, relative)

    compiled = controller.resume_conversational(
        run.id, compiler, compiler_fingerprint="unchanged-fixture", execute_plan=False,
    )
    replay = controller.resume_conversational(
        run.id, compiler, compiler_fingerprint="unchanged-fixture", execute_plan=False,
    )

    assert compiled.id == replay.id == run.id
    assert compiled.current_plan_id == replay.current_plan_id
    assert compiled.current_plan_id is not None
    assert len(model.requests) == 2
    assert all(tools == () for _, tools in model.requests)
    assert all("Route orders" in messages[1]["content"] for messages, _ in model.requests)
    assert answer in model.requests[1][0][1]["content"]
    assert answer not in model.requests[0][0][1]["content"]


def test_mock_default_contract_does_not_invoke_either_runtime_entry(tmp_path: Path) -> None:
    class NoCallsMock(MockRuntime):
        def run(self, *args, **kwargs):
            pytest.fail("mock contract should be generated without runtime execution")

        run_isolated = run

    result = RuntimeContractCompiler(NoCallsMock()).compile("Route orders", tmp_path)

    assert result.status == "compiled"
    assert result.evidence == ("repository mock compiler; no model response was used",)
