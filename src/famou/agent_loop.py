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

    def set_context(self, run_id: str, task_id: str, goal: str | None = None) -> None:
        """Attach durable identity for memory scoping and observability."""
        del goal
        self._run_id = run_id
        self._task_id = task_id
        self.tools.set_memory_scope(f"run:{run_id}")

    def set_session_path(self, path: str | Path) -> None:
        """Attach a stable run/task transcript path when session history is enabled."""
        if not self.session_history:
            return
        api_key = getattr(self.model, "api_key", None)
        redactions = (api_key,) if isinstance(api_key, str) and api_key else ()
        self._transcript = SessionTranscript(path, redactions=redactions)

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

    def run(
        self,
        prompt: str,
        workspace: Path,
        timeout: float | None = None,
        *,
        usage_ledger: UsageLedger | None = None,
        tool_steps_offset: int = 0,
    ) -> RuntimeResult:
        effective_timeout = self._profile_timeout(timeout)
        workspace.mkdir(parents=True, exist_ok=True)
        ledger = self._resolve_usage_ledger(usage_ledger)
        if isinstance(tool_steps_offset, bool) or not isinstance(tool_steps_offset, int) or tool_steps_offset < 0:
            raise ValueError("tool_steps_offset must be a non-negative integer")
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
            request_messages = self._budget_messages(messages, remaining, tool_steps, ledger)
            try:
                turn = self.model.complete(request_messages, self.tools.schemas(), remaining)
            except AgentInputRequired:
                raise
            except Exception as exc:
                self._emit(
                    "agent_runtime_failure",
                    {"phase": "model_turn", "error": _bounded_runtime_error(exc)},
                )
                raise
            if self.profile is not None:
                self._remaining_timeout(started, effective_timeout)
            model_turns += 1
            response_models.append(turn.response_model)
            usages.append(turn.usage)
            self._record_profile_usage(turn, ledger)
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
                metadata = {
                    "provider": "openai-compatible",
                    "mode": "agent-loop",
                    "turns": str(model_turns),
                    "session_history": str(self.session_history).lower(),
                    **self._telemetry_metadata(response_models, usages, ledger),
                }
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
                if self.profile is not None:
                    self._remaining_timeout(started, effective_timeout)
                tool_steps += 1
                self._last_tool_steps = tool_steps
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
        if turn.usage is None:
            if profile.max_total_tokens is not None or profile.max_cost_micros is not None:
                raise RuntimeExecutionError("model profile usage is required for token/cost ceilings")
            return
        try:
            snapshot = ledger.record(turn.usage)
        except ProfileBudgetExceeded as exc:
            raise ProfileBudgetFailure(exc.evidence) from exc
        except (TypeError, ValueError) as exc:
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
        if response_models and all(response_models) and len(set(response_models)) == 1:
            metadata["response_model"] = str(response_models[0])
        complete_usage = bool(usages) and all(value is not None for value in usages)
        if complete_usage:
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                metadata[key] = str(sum(value[key] for value in usages if value is not None))
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
