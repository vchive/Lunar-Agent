"""Shared invocation accounting and cooperative pauses must survive real failure shapes."""

from copy import deepcopy

import pytest

from famou.agent_loop import AgentLoopRuntime, ProfileBudgetFailure, StageBoundary
from famou.model_profile import UsageLedger
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.tools import LocalToolRegistry
from famou.transcript import SessionTranscript


def usage(input_tokens=2, output_tokens=1):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append(deepcopy(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response()
        return response


def test_shared_telemetry_uses_one_aggregate_for_rounds_tokens_cost_and_model(tmp_path):
    profile = ModelProfile(
        "shared", "fixture", max_total_tokens=100,
        input_cost_per_1k_micros=333, output_cost_per_1k_micros=333,
    )
    ledger = UsageLedger(profile)
    first = AgentLoopRuntime(
        Model(ModelTurn("master", usage=usage(), response_model="fixture-a")), profile=profile,
    )
    second = AgentLoopRuntime(
        Model(ModelTurn("build", usage=usage(1, 2), response_model="fixture-b")), profile=profile,
    )
    first.run("plan", tmp_path, usage_ledger=ledger)
    result = second.run("build", tmp_path, usage_ledger=ledger)

    assert result.metadata["turns"] == "2"
    assert result.metadata["invocation_turns"] == "1"
    assert result.metadata["input_tokens"] == result.metadata["output_tokens"] == "3"
    assert result.metadata["total_tokens"] == "6"
    assert result.metadata["cost_micros"] == "2"
    assert result.metadata["usage_scope"] == "aggregate"
    assert "response_model" not in result.metadata


@pytest.mark.parametrize("kind", ["token", "cost"])
def test_rejected_shared_usage_latches_across_runtime_instances(tmp_path, kind):
    profile = (
        ModelProfile("shared", "fixture", max_total_tokens=5)
        if kind == "token" else ModelProfile(
            "shared", "fixture", max_cost_micros=5,
            input_cost_per_1k_micros=1000, output_cost_per_1k_micros=1000,
        )
    )
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("master", usage=usage()), ModelTurn("over budget", usage=usage()))
    runtime = AgentLoopRuntime(model, profile=profile)
    runtime.run("master", tmp_path, usage_ledger=ledger)
    with pytest.raises(ProfileBudgetFailure) as rejected:
        runtime.run("build", tmp_path, usage_ledger=ledger)

    assert rejected.value.evidence.observed_usage.total_tokens == 6
    assert ledger.snapshot.total_tokens == 3
    assert not ledger.usage_complete
    assert not runtime.last_invocation.usage_complete
    successor_model = Model(ModelTurn("must not run", usage=usage(0, 0)))
    with pytest.raises(ProfileBudgetFailure) as blocked:
        AgentLoopRuntime(successor_model, profile=profile).run(
            "resume", tmp_path, usage_ledger=ledger,
        )
    assert blocked.value.evidence == rejected.value.evidence
    assert successor_model.requests == []


@pytest.mark.parametrize("kind", ["token", "cost"])
def test_exactly_exhausted_shared_ledger_stops_before_another_request(tmp_path, kind):
    profile = (
        ModelProfile("shared", "fixture", max_total_tokens=3)
        if kind == "token" else ModelProfile(
            "shared", "fixture", max_cost_micros=3,
            input_cost_per_1k_micros=1000, output_cost_per_1k_micros=1000,
        )
    )
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("allowed final", usage=usage()))
    runtime = AgentLoopRuntime(model, profile=profile)
    assert runtime.run("first", tmp_path, usage_ledger=ledger).text == "allowed final"
    with pytest.raises(ProfileBudgetFailure, match="exhausted"):
        runtime.run("second", tmp_path, usage_ledger=ledger)
    assert len(model.requests) == 1
    assert runtime.last_invocation.provider_requests == 0


def test_provider_timeout_marks_partial_ledger_unavailable_for_other_runtimes(tmp_path):
    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("master", usage=usage()), TimeoutError("provider request"))
    runtime = AgentLoopRuntime(model, profile=profile)
    runtime.run("master", tmp_path, usage_ledger=ledger)
    with pytest.raises(TimeoutError):
        runtime.run("build", tmp_path, usage_ledger=ledger)
    assert ledger.snapshot.total_tokens == 3
    assert not ledger.usage_complete
    assert runtime.last_invocation.provider_requests == 1
    assert runtime.last_invocation.responses_received == 0
    assert not runtime.last_invocation.usage_complete
    assert not runtime.last_invocation.boundary
    other_model = Model(ModelTurn("forbidden", usage=usage()))
    with pytest.raises(RuntimeExecutionError, match="aggregate usage is unavailable"):
        AgentLoopRuntime(other_model, profile=profile).run("resume", tmp_path, usage_ledger=ledger)
    assert not other_model.requests


@pytest.mark.parametrize("bad_usage", [None, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 9}])
def test_missing_or_malformed_response_usage_cannot_be_recovered_by_later_sample(tmp_path, bad_usage):
    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("master", usage=usage()), ModelTurn("unknown", usage=bad_usage))
    runtime = AgentLoopRuntime(model, profile=profile)
    runtime.run("master", tmp_path, usage_ledger=ledger)
    with pytest.raises(RuntimeExecutionError, match="usage"):
        runtime.run("build", tmp_path, usage_ledger=ledger)
    assert runtime.last_invocation.responses_received == 1
    assert not runtime.last_invocation.usage_complete
    ledger.record(usage())
    assert not ledger.usage_complete
    with pytest.raises(RuntimeExecutionError, match="aggregate usage is unavailable"):
        runtime.run("resume", tmp_path, usage_ledger=ledger)
    assert len(model.requests) == 2


def test_response_arriving_after_deadline_is_still_accounted(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("famou.agent_loop.time.monotonic", lambda: now[0])

    def late_response():
        now[0] = 11.0
        return ModelTurn("too late", usage=usage())

    profile = ModelProfile("shared", "fixture", timeout_seconds=10, max_total_tokens=30)
    ledger = UsageLedger(profile)
    runtime = AgentLoopRuntime(Model(late_response), profile=profile)
    with pytest.raises(RuntimeExecutionError, match="timed out"):
        runtime.run("build", tmp_path, usage_ledger=ledger)
    assert ledger.snapshot.total_tokens == 3
    assert runtime.last_invocation.responses_received == 1
    assert runtime.last_invocation.usage_complete
    assert not runtime.last_invocation.transcript_complete
    assert not runtime.last_invocation.boundary


def test_tool_overrun_counts_side_effect_and_persists_result_before_wall_check(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("famou.agent_loop.time.monotonic", lambda: now[0])

    class SlowTools(LocalToolRegistry):
        def execute(self, name, arguments, workspace):
            result = super().execute(name, arguments, workspace)
            now[0] = 11.0
            return result

    profile = ModelProfile("shared", "fixture", timeout_seconds=10, max_total_tokens=30)
    ledger = UsageLedger(profile)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    model = Model(ModelTurn(
        "", (ToolCall("save", "write_file", {"path": "solution.json", "content": "{}"}),),
        usage=usage(),
    ))
    runtime = AgentLoopRuntime(model, tools=SlowTools(), profile=profile, transcript=transcript)
    with pytest.raises(RuntimeExecutionError, match="timed out"):
        runtime.run("build", tmp_path, usage_ledger=ledger, tool_steps_offset=4)

    assert (tmp_path / "solution.json").read_text() == "{}"
    assert runtime.last_tool_steps == runtime.last_invocation.tool_steps == 5
    assert transcript.load()[-1]["tool_call_id"] == "save"
    assert runtime.last_invocation.usage_complete
    assert runtime.last_invocation.transcript_complete
    assert not runtime.last_invocation.boundary
    assert len(model.requests) == 1


def test_tool_exception_counts_attempt_without_claiming_paired_transcript(tmp_path):
    class BrokenTools(LocalToolRegistry):
        def execute(self, name, arguments, workspace):
            (workspace / "candidate").write_text("saved")
            raise OSError("after write")

    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("", (ToolCall("save", "write_file", {}),), usage=usage()))
    runtime = AgentLoopRuntime(
        model, tools=BrokenTools(), profile=profile,
        transcript=SessionTranscript(tmp_path / "transcript.jsonl"),
    )
    with pytest.raises(OSError, match="after write"):
        runtime.run("build", tmp_path, usage_ledger=ledger)
    assert runtime.last_tool_steps == 1
    assert (tmp_path / "candidate").read_text() == "saved"
    assert runtime.last_invocation.usage_complete
    assert not runtime.last_invocation.transcript_complete


def test_cooperative_boundary_waits_for_whole_durable_tool_round_and_reuses_ledger(tmp_path):
    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    calls = (
        ToolCall("save", "write_file", {"path": "solution.json", "content": "{}"}),
        ToolCall("verify", "read_file", {"path": "solution.json"}),
    )
    model = Model(
        ModelTurn("", calls, usage=usage(), response_model="fixture"),
        ModelTurn("ready", usage=usage(), response_model="fixture"),
    )
    runtime = AgentLoopRuntime(model, profile=profile, transcript=transcript)
    boundaries = []

    def stop(diagnostics):
        boundaries.append(diagnostics)
        assert [message["role"] for message in transcript.load()][-3:] == [
            "assistant", "tool", "tool",
        ]
        return True

    with pytest.raises(StageBoundary) as paused:
        runtime.run("build", tmp_path, usage_ledger=ledger, stage_boundary=stop)
    assert len(model.requests) == len(boundaries) == 1
    assert paused.value.diagnostics == runtime.last_invocation
    assert runtime.last_invocation.boundary
    assert runtime.last_invocation.usage_complete
    assert runtime.last_invocation.transcript_complete
    assert runtime.last_invocation.tool_steps == 2
    result = runtime.run(
        "finish", tmp_path, usage_ledger=ledger, tool_steps_offset=runtime.last_tool_steps,
        stage_boundary=lambda diagnostics: pytest.fail("final text needs no boundary"),
    )
    assert result.text == "ready"
    assert result.metadata["total_tokens"] == "6"
    assert result.metadata["turns"] == "2"
    assert result.metadata["tool_steps"] == "2"
    assert result.metadata["response_model"] == "fixture"
    assert runtime.last_invocation.transcript_complete
    assert not runtime.last_invocation.boundary
    replayed = model.requests[-1]
    assert [message.get("tool_call_id") for message in replayed if message["role"] == "tool"] == [
        "save", "verify",
    ]


def test_compaction_that_splits_tool_round_cannot_authorize_stage_boundary(tmp_path):
    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl", max_messages=2)
    model = Model(ModelTurn(
        "", (ToolCall("one", "list_dir", {}), ToolCall("two", "list_dir", {})), usage=usage(),
    ))
    runtime = AgentLoopRuntime(model, profile=profile, transcript=transcript)
    with pytest.raises(RuntimeExecutionError, match="paired transcript") as failure:
        runtime.run("build", tmp_path, usage_ledger=ledger, stage_boundary=lambda diagnostics: True)
    assert not isinstance(failure.value, StageBoundary)
    assert not runtime.last_invocation.transcript_complete
    assert not runtime.last_invocation.boundary
    assert len(model.requests) == 1


def test_boundary_requires_shared_ledger_and_durable_transcript_before_spending(tmp_path):
    model = Model()
    runtime = AgentLoopRuntime(model)
    with pytest.raises(ValueError, match="explicit ledger and durable transcript"):
        runtime.run("build", tmp_path, stage_boundary=lambda diagnostics: True)
    assert model.requests == []


def test_confined_transcript_tool_directory_swap_fails_before_external_append(tmp_path):
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    outside_transcript = external / "session.jsonl"
    outside_transcript.write_text("external transcript must stay unchanged\n")
    workflow = workspace / ".workflow"

    class SwappingTools(LocalToolRegistry):
        def execute(self, name, arguments, workspace):
            result = super().execute(name, arguments, workspace)
            workflow.rename(workspace / ".workflow.saved")
            workflow.symlink_to(external, target_is_directory=True)
            return result

    profile = ModelProfile("shared", "fixture", max_total_tokens=30)
    ledger = UsageLedger(profile)
    model = Model(ModelTurn("", (ToolCall("swap", "list_dir", {}),), usage=usage()))
    runtime = AgentLoopRuntime(
        model, tools=SwappingTools(), profile=profile, session_history=True,
    )
    runtime.set_session_path(workflow / "session.jsonl", confined_workspace=workspace)
    with pytest.raises(ValueError, match="symlink"):
        runtime.run("build", workspace, usage_ledger=ledger)

    assert outside_transcript.read_text() == "external transcript must stay unchanged\n"
    assert list(external.iterdir()) == [outside_transcript]
    assert runtime.last_tool_steps == 1
    assert not runtime.last_invocation.transcript_complete
    assert len(model.requests) == 1


@pytest.mark.parametrize("kind", ["outside", "traversal", "directory_symlink", "file_symlink"])
def test_confined_transcript_rejects_unsafe_path_at_initialization(tmp_path, kind):
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    target = external / "session.jsonl"
    target.write_text("private transcript\n")
    if kind == "outside":
        path = target
    elif kind == "traversal":
        path = workspace / ".." / "external" / "session.jsonl"
    elif kind == "directory_symlink":
        (workspace / "linked").symlink_to(external, target_is_directory=True)
        path = workspace / "linked" / "session.jsonl"
    else:
        path = workspace / "session.jsonl"
        path.symlink_to(target)
    with pytest.raises(ValueError, match=r"inside|\.\.|symlink"):
        SessionTranscript(path, confined_workspace=workspace)
    assert target.read_text() == "private transcript\n"


def test_confined_transcript_rechecks_leaf_before_loading(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    transcript = SessionTranscript("history/session.jsonl", confined_workspace=workspace)
    transcript.append({"role": "user", "content": "local"})
    assert transcript.load() == [{"role": "user", "content": "local"}]
    external = tmp_path / "private.jsonl"
    external.write_text('{"role":"user","content":"private"}\n')
    transcript.path.unlink()
    transcript.path.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        transcript.load()


def test_confined_transcript_temporary_file_is_exclusive_and_nofollow(tmp_path, monkeypatch):
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    transcript = SessionTranscript("session.jsonl", confined_workspace=workspace)
    external = tmp_path / "private"
    external.write_text("unchanged")
    temporary = workspace / ".session.jsonl.fixed.tmp"
    temporary.symlink_to(external)
    monkeypatch.setattr("famou.transcript.uuid.uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(FileExistsError):
        transcript.append({"role": "user", "content": "must not escape"})
    assert external.read_text() == "unchanged"
    assert not transcript.path.exists()
    assert temporary.is_symlink()
