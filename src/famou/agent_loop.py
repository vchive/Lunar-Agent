"""Hermes-inspired continuous tool loop layered on a model Runtime.

This is an execution primitive, not a WebAgent stage machine. The durable controller owns
scheduling and recovery; this runtime owns one conversational session, local tools, and memory.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path

from .memory import MemoryStore
from .model_profile import BudgetFailureEvidence, ProfileBudgetExceeded, UsageLedger
from .profiles import ModelProfile
from .runtime import ModelTurn, OpenAICompatibleRuntime, RuntimeExecutionError, RuntimeResult
from .tools import LocalToolRegistry
from .transcript import SessionTranscript

HERMES_SYSTEM_PROMPT = """You are Lunar-Agent, a local-first general-purpose assistant inspired by
Hermes-style long-running sessions. Continue from the supplied goal and any relevant durable memory.
Use tools to inspect and change files, run explicitly permitted commands, and record useful facts in
memory. Work only inside the supplied task workspace. Be honest about what you actually did. Keep
the user informed with a concise final summary, including files changed and checks performed. When
memory tools are available, recall relevant notes before continuing old work and remember only
concise, reusable facts or decisions.
"""
ISOLATED_SYSTEM_PROMPT = """You are executing one stateless Lunar-Agent protocol step. Follow the
user message exactly, return only its requested machine-readable response, and do not use tools,
memory, session history, or unstated external context.
"""

# Compatibility alias for callers that imported the earlier experimental name.
BUILD_SYSTEM_PROMPT = HERMES_SYSTEM_PROMPT
_SECRET_TEXT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


def _bounded_runtime_error(error: object, limit: int = 512) -> str:
    text = _SECRET_TEXT.sub("[REDACTED]", " ".join(str(error).split()))
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "\n[truncated]"
    budget = max(1, limit - len(suffix.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


class AgentInputRequired(RuntimeExecutionError):
    """Raised when a session intentionally pauses for a user/parent-Agent answer."""

    def __init__(self, question: str, options: tuple[str, ...] = ()) -> None:
        super().__init__(question)
        self.question = question
        self.options = options


class ProfileBudgetFailure(RuntimeExecutionError):
    """A repository-owned profile failure carrying reported usage for safe diagnostics."""

    def __init__(self, evidence: BudgetFailureEvidence) -> None:
        self.evidence = evidence
        super().__init__(f"model profile budget {evidence.state}: {evidence.limit}")


@dataclass(frozen=True)
class InvocationDiagnostics:
    """Observed invocation state, including uncertainty after an interrupted request."""

    provider_requests: int = 0
    responses_received: int = 0
    usage_complete: bool = True
    transcript_complete: bool = False
    tool_steps: int = 0
    elapsed_seconds: float = 0.0
    boundary: bool = False


class StageBoundary(RuntimeExecutionError):
    """Cooperative pause after a complete, durably paired tool round."""

    def __init__(self, diagnostics: InvocationDiagnostics) -> None:
        self.diagnostics = diagnostics
        super().__init__("agent loop paused at a durable stage boundary")


class AgentLoopRuntime:
    """Execute one bounded Hermes-style session with optional persistent memory."""

    name = "agent-loop"

    def __init__(
        self,
        model: OpenAICompatibleRuntime,
        tools: LocalToolRegistry | None = None,
        max_steps: int = 40,
        system_prompt: str = HERMES_SYSTEM_PROMPT,
        memory: MemoryStore | None = None,
        session_history: bool = False,
        transcript: SessionTranscript | None = None,
        profile: ModelProfile | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model = model
        self.memory = memory
        self.tools = tools or LocalToolRegistry(memory=memory)
        if memory is not None and self.tools.memory is None:
            self.tools.memory = memory
        api_key = getattr(model, "api_key", None)
        if isinstance(api_key, str) and api_key and api_key not in self.tools.redactions:
            self.tools.redactions = (*self.tools.redactions, api_key)
        self.max_steps = max_steps
        if profile is not None and not isinstance(profile, ModelProfile):
            raise TypeError("profile must be a ModelProfile")
        self.profile = profile
        if profile is not None:
            self.max_steps = min(self.max_steps, profile.max_steps)
        self.system_prompt = system_prompt
        self.session_history = session_history or transcript is not None
        self._transcript = transcript
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None
        self._run_id: str | None = None
        self._task_id: str | None = None
        self._last_tool_steps = 0
        self._last_invocation = InvocationDiagnostics()

    def set_context(self, run_id: str, task_id: str, goal: str | None = None) -> None:
        """Attach durable identity for memory scoping and observability."""
        del goal
        self._run_id = run_id
        self._task_id = task_id
        self.tools.set_memory_scope(f"run:{run_id}")

    def set_session_path(
        self, path: str | Path, *, confined_workspace: Path | None = None,
    ) -> None:
        """Attach a stable run/task transcript path when session history is enabled."""
        if not self.session_history:
            return
        api_key = getattr(self.model, "api_key", None)
        redactions = (api_key,) if isinstance(api_key, str) and api_key else ()
        self._transcript = SessionTranscript(
            path, redactions=redactions, confined_workspace=confined_workspace,
        )

    def session_path(self) -> Path | None:
        return self._transcript.path if self._transcript is not None else None

    def set_event_sink(self, sink: Callable[[str, dict[str, object]], None] | None) -> None:
        self._event_sink = sink

    def set_process_observer(self, observer: Callable[[int, int | None], None] | None) -> None:
        self.model.set_process_observer(observer)

    def process_info(self) -> tuple[int | None, int | None]:
        return self.model.process_info()

    def cancel(self) -> None:
        self.model.cancel()

    @property
    def last_tool_steps(self) -> int:
        """Tool calls observed by the most recent invocation, including any offset."""
        return self._last_tool_steps

    @property
    def last_invocation(self) -> InvocationDiagnostics:
        return self._last_invocation

    def run(
        self,
        prompt: str,
        workspace: Path,
        timeout: float | None = None,
        *,
        usage_ledger: UsageLedger | None = None,
        tool_steps_offset: int = 0,
        stage_boundary: Callable[[InvocationDiagnostics], bool] | None = None,
    ) -> RuntimeResult:
        effective_timeout = self._profile_timeout(timeout)
        workspace.mkdir(parents=True, exist_ok=True)
        ledger = self._resolve_usage_ledger(usage_ledger)
        if isinstance(tool_steps_offset, bool) or not isinstance(tool_steps_offset, int) or tool_steps_offset < 0:
            raise ValueError("tool_steps_offset must be a non-negative integer")
        if stage_boundary is not None and (usage_ledger is None or self._transcript is None):
            raise ValueError("stage boundaries require an explicit ledger and durable transcript")
        self._last_invocation = InvocationDiagnostics(
            tool_steps=tool_steps_offset,
            usage_complete=ledger.usage_complete if ledger is not None else False,
        )
        messages = self._initial_messages(prompt)
        # Memory is exposed through explicit model tool calls. We do not inject local notes into a
        # request implicitly: sending durable user context to a configured endpoint must remain an
        # intentional, per-run choice.
        artifacts: list[str] = []
        started = time.monotonic()
        model_turns = 0
        tool_steps = tool_steps_offset
        self._last_tool_steps = tool_steps
        response_models: list[str | None] = []
        usages: list[dict[str, int] | None] = []
        while True:
            remaining = self._remaining_timeout(started, effective_timeout)
            self._check_profile_request(ledger, require_complete=usage_ledger is not None)
            if model_turns and stage_boundary is not None:
                self._update_invocation(
                    started,
                    transcript_complete=self._durable_transcript_complete(messages),
                )
                if stage_boundary(self.last_invocation):
                    if not self.last_invocation.usage_complete or not self.last_invocation.transcript_complete:
                        raise RuntimeExecutionError("stage boundary requires complete usage and paired transcript")
                    self._update_invocation(started, boundary=True)
                    raise StageBoundary(self.last_invocation)
            request_messages = self._budget_messages(messages, remaining, tool_steps, ledger)
            self._update_invocation(
                started,
                provider_requests=self.last_invocation.provider_requests + 1,
                usage_complete=False,
                transcript_complete=False,
            )
            try:
                turn = self.model.complete(request_messages, self.tools.schemas(), remaining)
            except AgentInputRequired:
                if ledger is not None:
                    ledger.mark_usage_unavailable()
                raise
            except Exception as exc:
                if ledger is not None:
                    ledger.mark_usage_unavailable()
                self._emit(
                    "agent_runtime_failure",
                    {"phase": "model_turn", "error": _bounded_runtime_error(exc)},
                )
                raise
            model_turns += 1
            response_models.append(turn.response_model)
            usages.append(turn.usage)
            self._update_invocation(started, responses_received=model_turns)
            try:
                self._record_profile_usage(turn, ledger)
            finally:
                self._update_invocation(
                    started,
                    usage_complete=ledger.usage_complete if ledger is not None else False,
                )
            self._emit(
                "agent_model_turn",
                {
                    "turn": model_turns,
                    "tool_call_count": len(turn.tool_calls),
                    "has_text": bool(turn.text),
                    "tool_steps": tool_steps,
                },
            )
            if self.profile is not None:
                self._remaining_timeout(started, effective_timeout)
            if not turn.tool_calls:
                if not turn.text:
                    raise RuntimeExecutionError("agent loop ended without a final text result")
                final_message = {"role": "assistant", "content": turn.text}
                self._append_transcript(final_message)
                self._update_invocation(
                    started,
                    transcript_complete=self._durable_transcript_complete([*messages, final_message]),
                )
                metadata = {
                    "provider": "openai-compatible",
                    "mode": "agent-loop",
                    "turns": str(ledger.snapshot.rounds if usage_ledger is not None else model_turns),
                    "session_history": str(self.session_history).lower(),
                    **self._telemetry_metadata(response_models, usages, ledger),
                }
                if usage_ledger is not None:
                    metadata["invocation_turns"] = str(model_turns)
                    metadata["tool_steps"] = str(tool_steps)
                    metadata["usage_scope"] = "aggregate"
                return RuntimeResult(
                    text=turn.text,
                    artifacts=tuple(dict.fromkeys(artifacts)),
                    metadata=metadata,
                )
            if tool_steps + len(turn.tool_calls) > self.max_steps:
                self._emit(
                    "agent_step_limit_reached",
                    {"max_steps": self.max_steps, "tool_steps": tool_steps},
                )
                raise RuntimeExecutionError(f"agent loop exceeded max steps ({self.max_steps})")
            messages.append(self._assistant_message(turn))
            self._append_transcript(messages[-1])
            for call in turn.tool_calls:
                if self.profile is not None:
                    self._remaining_timeout(started, effective_timeout)
                # An attempted tool can already have side effects when it raises or overruns.
                tool_steps += 1
                self._last_tool_steps = tool_steps
                self._update_invocation(started, tool_steps=tool_steps)
                try:
                    deadline_scope = (
                        self.tools.execution_deadline(started + effective_timeout)
                        if self.profile is not None and effective_timeout is not None
                        else nullcontext()
                    )
                    with deadline_scope:
                        result = self.tools.execute(call.name, call.arguments, workspace)
                except Exception as exc:
                    self._emit(
                        "agent_runtime_failure",
                        {"phase": "tool", "tool": call.name, "error": _bounded_runtime_error(exc)},
                    )
                    raise
                artifacts.extend(result.artifacts)
                self._emit(
                    "agent_tool_result",
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "success": result.success,
                        "artifact_count": len(result.artifacts),
                        "output_bytes": len(result.output.encode("utf-8")),
                        "awaiting_input": result.awaiting_input,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.output,
                    }
                )
                self._append_transcript(messages[-1])
                self._update_invocation(
                    started, transcript_complete=self._durable_transcript_complete(messages),
                )
                if self.profile is not None:
                    self._remaining_timeout(started, effective_timeout)
                if result.awaiting_input:
                    raise AgentInputRequired(
                        result.input_question or result.output[:8_000], result.input_options
                    )

    def _budget_messages(
        self, messages: list[dict[str, object]], remaining: float | None,
        tool_steps: int, ledger: UsageLedger | None,
    ) -> list[dict[str, object]]:
        """Refresh advisory budget facts on a request copy, never on replayable history."""
        if ledger is None:
            return messages
        profile = ledger.profile
        usage = ledger.snapshot
        command_timeout = (
            min(self.tools.command_timeout, remaining)
            if self.tools.allow_exec and remaining is not None else None
        )
        snapshot = {
            "schema_version": "1",
            "remaining_seconds": math.floor(remaining * 1000) / 1000 if remaining is not None else None,
            "tool_steps_remaining": max(0, self.max_steps - tool_steps),
            "command_timeout_seconds": (
                math.floor(command_timeout * 1000) / 1000 if command_timeout is not None else None
            ),
            "tokens_remaining": (
                profile.max_total_tokens - usage.total_tokens
                if profile.max_total_tokens is not None else None
            ),
            "cost_micros_remaining": (
                profile.max_cost_micros - usage.cost_micros
                if profile.max_cost_micros is not None and usage.cost_micros is not None else None
            ),
        }
        guidance = (
            "\n\n<lunar_runtime_budget>\n" + json.dumps(snapshot, sort_keys=True)
            + "\n</lunar_runtime_budget>\n"
            "Advisory snapshot before this request: model and tool time reduces these windows. "
            "Spend allowances count accepted prior responses; this request also consumes them. "
            "Null spend means no configured ceiling; null command time means execution is unavailable. "
            "Tool steps count individual calls, not model turns. If solving for files, save a complete "
            "candidate before expensive refinement and preserve it while improving. write_file publishes "
            "one complete replacement atomically. Generated scripts must save their own incremental "
            "outputs atomically (temporary file then replace), profile expensive work, and use an internal "
            "soft deadline below the remaining command window, leaving time to save and finish. "
            "No complete candidate may exist; do not present partial/empty output as a valid solution. "
            "Saved files still require independent verification."
        )
        copied = list(messages)
        for index, message in enumerate(copied):
            if message.get("role") == "system":
                copied[index] = {**message, "content": str(message.get("content") or "") + guidance}
                break
        return copied

    def run_isolated(
        self, prompt: str, workspace: Path, timeout: float | None = None
    ) -> RuntimeResult:
        """Run one stateless, tool-free model turn for a trust-boundary decision.

        Evaluator compilation and adversarial audit must not inherit the user's durable transcript,
        memory tools, or a previous compiler response. Keeping this primitive on the repository-
        owned loop lets protocol code request that boundary without depending on model internals.
        """
        effective_timeout = self._profile_timeout(timeout)
        workspace.mkdir(parents=True, exist_ok=True)
        ledger = UsageLedger(self.profile) if self.profile is not None else None
        started = time.monotonic()
        turn = self.model.complete(
            [
                {"role": "system", "content": ISOLATED_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            (),
            self._remaining_timeout(started, effective_timeout)
            if self.profile is not None else timeout,
        )
        if self.profile is not None:
            self._remaining_timeout(started, effective_timeout)
        self._record_profile_usage(turn, ledger)
        if turn.tool_calls:
            raise RuntimeExecutionError("isolated agent turn returned tool calls")
        if not turn.text:
            raise RuntimeExecutionError("isolated agent turn returned empty content")
        return RuntimeResult(
            text=turn.text,
            metadata={
                "provider": "openai-compatible",
                "mode": "agent-loop-isolated",
                "session_history": "false",
                **(
                    self._telemetry_metadata([turn.response_model], [turn.usage], ledger)
                    if ledger is not None else {}
                ),
            },
        )

    def _resolve_usage_ledger(self, usage_ledger: UsageLedger | None) -> UsageLedger | None:
        """Return a per-call ledger by default, or validate an explicit staged ledger."""
        if usage_ledger is None:
            return UsageLedger(self.profile) if self.profile is not None else None
        if self.profile is None:
            raise ValueError("an explicit usage ledger requires a model profile")
        if not isinstance(usage_ledger, UsageLedger) or usage_ledger.profile != self.profile:
            raise ValueError("usage ledger profile does not match runtime profile")
        return usage_ledger

    @staticmethod
    def _check_profile_request(ledger: UsageLedger | None, *, require_complete: bool) -> None:
        if ledger is None:
            return
        try:
            ledger.check_request(require_complete=require_complete)
        except ProfileBudgetExceeded as exc:
            raise ProfileBudgetFailure(exc.evidence) from exc
        except ValueError as exc:
            raise RuntimeExecutionError(str(exc)) from exc

    def _update_invocation(self, started: float, **changes: object) -> None:
        self._last_invocation = replace(
            self._last_invocation,
            elapsed_seconds=max(0.0, time.monotonic() - started),
            **changes,
        )

    def _durable_transcript_complete(self, messages: list[dict[str, object]]) -> bool:
        """Reject compaction cuts, missing appends, and unfinished native tool batches."""
        if self._transcript is None:
            return False
        durable = self._transcript.load()
        if not durable or not messages:
            return False
        if durable[-1].get("role") != messages[-1].get("role"):
            return False
        if durable[-1].get("tool_call_id") != messages[-1].get("tool_call_id"):
            return False
        pending: set[str] = set()
        for message in durable:
            if message.get("role") == "tool":
                call_id = message.get("tool_call_id")
                if not isinstance(call_id, str) or call_id not in pending:
                    return False
                pending.remove(call_id)
                continue
            if pending:
                return False
            calls = message.get("tool_calls")
            if calls is not None:
                if message.get("role") != "assistant" or not isinstance(calls, list):
                    return False
                for call in calls:
                    if not isinstance(call, dict):
                        return False
                    call_id = call.get("id")
                    if not isinstance(call_id, str) or not call_id or call_id in pending:
                        return False
                    pending.add(call_id)
        return not pending

    def _profile_timeout(self, timeout: float | None) -> float | None:
        if self.profile is None:
            return timeout
        if timeout is None:
            return self.profile.timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise RuntimeExecutionError("model profile timeout must be finite and positive")
        return min(timeout, self.profile.timeout_seconds)

    @staticmethod
    def _record_profile_usage(turn: ModelTurn, ledger: UsageLedger | None) -> None:
        if ledger is None:
            return
        profile = ledger.profile
        ledger.observe_response_model(turn.response_model)
        if turn.usage is None:
            ledger.mark_usage_unavailable()
            if profile.max_total_tokens is not None or profile.max_cost_micros is not None:
                raise RuntimeExecutionError("model profile usage is required for token/cost ceilings")
            return
        try:
            snapshot = ledger.record(turn.usage)
        except ProfileBudgetExceeded as exc:
            raise ProfileBudgetFailure(exc.evidence) from exc
        except (TypeError, ValueError) as exc:
            ledger.mark_usage_unavailable()
            raise RuntimeExecutionError("model profile usage is invalid") from exc
        # Equality is valid for a final answer, but tool calls require another model turn to
        # finish. Stop before tool side effects when the accepted response has used the ceiling.
        if turn.tool_calls:
            for name, actual, maximum in (
                ("max_total_tokens", snapshot.total_tokens, profile.max_total_tokens),
                ("max_cost_micros", snapshot.cost_micros, profile.max_cost_micros),
            ):
                if maximum is not None and actual is not None and actual >= maximum:
                    raise ProfileBudgetFailure(BudgetFailureEvidence(
                        limit=name, state="exhausted", maximum=maximum,
                        accepted_usage=snapshot, observed_usage=snapshot, trigger_recorded=True,
                    ))

    @staticmethod
    def _telemetry_metadata(
        response_models: list[str | None],
        usages: list[dict[str, int] | None],
        ledger: UsageLedger | None,
    ) -> dict[str, str]:
        metadata: dict[str, str] = {}
        if ledger is not None and ledger.response_model is not None:
            metadata["response_model"] = ledger.response_model
        elif ledger is None and response_models and all(response_models) and len(set(response_models)) == 1:
            metadata["response_model"] = str(response_models[0])
        complete_usage = bool(usages) and all(value is not None for value in usages)
        if ledger is not None:
            complete_usage = complete_usage and ledger.usage_complete
        if complete_usage:
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                metadata[key] = str(
                    getattr(ledger.snapshot, key) if ledger is not None
                    else sum(value[key] for value in usages if value is not None)
                )
        if ledger is not None:
            metadata["profile"] = ledger.profile.name
            snapshot = ledger.snapshot
            if complete_usage and snapshot.cost_micros is not None:
                metadata["cost_micros"] = str(snapshot.cost_micros)
        return metadata

    @staticmethod
    def _remaining_timeout(started: float, timeout: float | None) -> float | None:
        if timeout is None:
            return None
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeExecutionError("agent loop timed out before the next model turn")
        return remaining

    @staticmethod
    def _assistant_message(turn: ModelTurn) -> dict[str, object]:
        tool_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in turn.tool_calls
        ]
        return {"role": "assistant", "content": turn.text or None, "tool_calls": tool_calls}

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, payload)

    def _initial_messages(self, prompt: str) -> list[dict[str, object]]:
        if not self.session_history or self._transcript is None:
            return [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ]
        loaded = self._transcript.load()
        messages = list(loaded)
        has_system = any(message.get("role") == "system" for message in messages)
        if not has_system:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
            if not loaded:
                self._append_transcript(messages[0])
        appended_prompt = not messages or messages[-1].get("content") != prompt or messages[-1].get("role") != "user"
        if appended_prompt:
            messages.append({"role": "user", "content": prompt})
        # Persist only the newly appended continuation prompt; the loader already returned the
        # previous bounded messages and writing them again would duplicate the transcript.
        if appended_prompt:
            self._append_transcript(messages[-1])
        return messages

    def _append_transcript(self, message: dict[str, object]) -> None:
        if self.session_history and self._transcript is not None:
            self._transcript.append(message)


class HermesSessionRuntime(AgentLoopRuntime):
    """Named product-facing variant of :class:`AgentLoopRuntime`.

    The implementation is repository-owned; the name communicates the intended interaction model
    without implying that the user's Hermes package or configuration is imported.
    """

    name = "hermes-session"
