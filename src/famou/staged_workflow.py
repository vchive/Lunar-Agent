"""Opt-in, single-process stages sharing one attempt and one resource envelope.

Only cooperative boundaries between durable, complete tool rounds can resume. Provider failures
remain failures: accepted usage alone cannot account for an interrupted provider request.
Receipts and evaluation remain the responsibility of the existing effect adapters and trial runner.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .agent_loop import AgentLoopRuntime, StageBoundary
from .model_profile import UsageLedger
from .runtime import RuntimeExecutionError, RuntimeResult
from .workflow_checkpoint import (
    AggregateUsage,
    WorkflowCheckpointError,
    WorkflowController,
    WorkflowManifest,
)


def _profile_digest(agent: AgentLoopRuntime) -> str:
    raw = json.dumps(agent.profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_master_response(text: str) -> dict[str, object]:
    """Accept one whole object or one explicit JSON fence, never select or repair a substring."""
    try:
        size = len(text.encode("utf-8"))
    except (AttributeError, UnicodeError):
        raise WorkflowCheckpointError("master response is not valid UTF-8 text") from None
    if size > 128 * 1024:
        raise WorkflowCheckpointError("master response exceeds bounded size")
    candidate = text.strip(" \t\r\n")
    if not candidate.startswith("{"):
        lines = text.split("\n")
        delimiters = [(index, line.removesuffix("\r").strip(" \t"))
                      for index, line in enumerate(lines)
                      if line.lstrip(" \t").startswith(("```", "~~~"))]
        if len(delimiters) != 2 or delimiters[0][1] != "```json" or delimiters[1][1] != "```":
            raise WorkflowCheckpointError("master response must contain one unambiguous JSON object")
        start, end = delimiters[0][0], delimiters[1][0]
        outside = "\n".join([*lines[:start], *lines[end + 1:]])
        if any(character in outside for character in "{}[]"):
            raise WorkflowCheckpointError("master response contains competing structured content")
        candidate = "\n".join(lines[start + 1:end])

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object member")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("nonfinite JSON number")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite JSON number")
        return result

    try:
        parsed = json.loads(candidate, object_pairs_hook=unique_object,
                            parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, RecursionError):
        raise WorkflowCheckpointError("master response contains invalid JSON") from None
    if not isinstance(parsed, dict):
        raise WorkflowCheckpointError("master response must be a JSON object")
    return parsed


@dataclass(frozen=True)
class StagePolicy:
    """Reservations in seconds, always inside the manifest's aggregate wall limit."""

    master_seconds: float
    build_seconds: float
    reserve_seconds: float
    checkpoint_after_rounds: int | None = None

    def __post_init__(self) -> None:
        for value in (self.master_seconds, self.build_seconds, self.reserve_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise WorkflowCheckpointError("stage reservations must be finite and positive")
        if self.checkpoint_after_rounds is not None and (
            type(self.checkpoint_after_rounds) is not int or self.checkpoint_after_rounds < 1
        ):
            raise WorkflowCheckpointError("checkpoint_after_rounds must be positive or null")

    @classmethod
    def from_dict(cls, value: object) -> StagePolicy:
        if not isinstance(value, dict) or set(value) != {
            "master_seconds", "build_seconds", "reserve_seconds", "checkpoint_after_rounds",
        }:
            raise WorkflowCheckpointError("invalid stage policy fields")
        return cls(**value)


@dataclass(frozen=True)
class StagedWorkflowConfig:
    manifest: WorkflowManifest
    policy: StagePolicy

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, WorkflowManifest) or not isinstance(self.policy, StagePolicy):
            raise WorkflowCheckpointError("staged config requires a typed manifest and policy")
        if self.policy.master_seconds + self.policy.build_seconds + self.policy.reserve_seconds >= self.manifest.ceilings["max_wall_seconds"]:
            raise WorkflowCheckpointError("stage reservations must leave time for resume")

    def to_dict(self) -> dict[str, object]:
        return {"manifest": self.manifest.to_dict(), "policy": asdict(self.policy)}

    @classmethod
    def from_dict(cls, value: object) -> StagedWorkflowConfig:
        if not isinstance(value, dict) or set(value) != {"manifest", "policy"}:
            raise WorkflowCheckpointError("invalid staged workflow config fields")
        return cls(WorkflowManifest.from_dict(value["manifest"]), StagePolicy.from_dict(value["policy"]))

    @classmethod
    def load(cls, path: Path) -> StagedWorkflowConfig:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise WorkflowCheckpointError("workflow config must be a bounded regular file")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class StagedRunResult:
    status: str
    checkpoint_number: int
    resumed: bool
    runtime: RuntimeResult | None = None


class StagedWorkflowRunner:
    """One fresh attempt; continuation is explicit and stays in this process.

    Restoring a process from an accepted-only usage snapshot is intentionally unsupported. No run
    or resume parameter can replace the original prompt, ledger, schedule, or aggregate deadline.
    """

    def __init__(
        self, controller: WorkflowController, agent: AgentLoopRuntime, workspace: str | Path,
        *, policy: StagePolicy, usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.controller, self.agent = controller, agent
        self.workspace = Path(workspace).expanduser().absolute()
        if self.workspace != controller.workspace or self.workspace.is_symlink():
            raise WorkflowCheckpointError("runner workspace does not match controller")
        if agent.profile is None or _profile_digest(agent) != controller.manifest.model_profile_sha256:
            raise WorkflowCheckpointError("runner model profile does not match manifest")
        ceilings = controller.manifest.ceilings
        if (ceilings["max_tool_steps"] != agent.max_steps
            or ceilings["max_total_tokens"] != agent.profile.max_total_tokens
            or ceilings["max_cost_micros"] != agent.profile.max_cost_micros
            or ceilings["max_wall_seconds"] > agent.profile.timeout_seconds):
            raise WorkflowCheckpointError("runner aggregate limits do not match profile")
        self.config = StagedWorkflowConfig(controller.manifest, policy)
        self.usage_ledger = usage_ledger if usage_ledger is not None else UsageLedger(agent.profile)
        if self.usage_ledger.profile != agent.profile or self.usage_ledger.snapshot.rounds:
            raise WorkflowCheckpointError("runner requires a fresh ledger with the same profile")
        if controller.state()["stage"] != "created":
            raise WorkflowCheckpointError("staged runner requires a fresh attempt; process restart is unsupported")
        self._started: float | None = None
        self._prompt: str | None = None
        self._steps = 0
        self._checkpoint_number: int | None = None
        self._resumed = False
        self._can_resume = False
        self._expected: list[str] = []
        self._master_sha: str | None = None
        self._checkpoint_sha: str | None = None
        self._build_transcript = self.workspace / "workflow" / "session-transcript.jsonl"

    def _remaining(self) -> float:
        if self._started is None:
            raise WorkflowCheckpointError("staged run has not started")
        remaining = self.config.manifest.ceilings["max_wall_seconds"] - (time.monotonic() - self._started)
        remaining -= self.config.policy.reserve_seconds
        if remaining <= 0:
            raise RuntimeExecutionError("staged aggregate deadline exhausted")
        return remaining

    def _attach_transcript(self, path: Path) -> None:
        self.controller.assert_paths_safe()
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise WorkflowCheckpointError("unsafe staged transcript")
        self.agent.session_history = True
        self.agent.set_session_path(path, confined_workspace=self.workspace)

    def run(self, prompt: str) -> StagedRunResult:
        if self._started is not None or self.controller.state()["stage"] != "created":
            raise WorkflowCheckpointError("staged attempt may start only once")
        self._started, self._prompt = time.monotonic(), prompt
        self.controller._write_new(self.workspace / "workflow" / "config.json", self.config.to_dict())
        self.controller.transition("master_running")
        self._attach_transcript(self.workspace / "workflow" / "master-transcript.jsonl")
        master_prompt = prompt + '''\n\nPlanning stage: inspect public inputs if needed, then return ONLY a JSON object
with exactly {"plan": ["ordered implementation steps"], "expected_paths": ["solution output paths"]}.
Include _agent_summary.md in expected_paths. Paths must be relative output files outside case/ and
workflow/. Do not write workflow control files or receipt files. The build stage will receive this
plan and the original public task. Plan to save a complete candidate before expensive refinement,
verify public constraints, and preserve improvements atomically. No result is guaranteed.
'''
        master = self.agent.run(
            master_prompt, self.workspace,
            timeout=min(self.config.policy.master_seconds, self._remaining()),
            usage_ledger=self.usage_ledger,
        )
        self._steps = self.agent.last_tool_steps
        self.controller.record_usage(self._usage())
        parsed = _parse_master_response(master.text)
        if not isinstance(parsed, dict) or set(parsed) != {"plan", "expected_paths"}:
            raise WorkflowCheckpointError("master must return plan and expected_paths")
        paths = parsed["expected_paths"]
        if not isinstance(paths, list) or "_agent_summary.md" not in paths or any(
            not isinstance(path, str) or path.split("/")[0] in {"workflow", "case"}
            or path in {"request.json", "receipt.json"} for path in paths
        ):
            raise WorkflowCheckpointError("master must declare safe output paths")
        secret = getattr(self.agent.model, "api_key", None)
        plan = parsed["plan"]
        if isinstance(secret, str) and secret and isinstance(plan, list):
            plan = [item.replace(secret, "[REDACTED]") if isinstance(item, str) else item for item in plan]
        master_record = self.controller.write_master(plan, paths)
        self._expected = master_record["expected_paths"]
        self._master_sha = master_record["plan_sha256"]
        # Start build with the sanitized plan and original request, not the master's raw history.
        if self._build_transcript.exists() or self._build_transcript.is_symlink():
            raise WorkflowCheckpointError("build transcript already exists")
        self._attach_transcript(self._build_transcript)
        self.controller.transition("build_running")
        return self._build(resumed=False)

    def _validated_master(self) -> dict[str, object]:
        if self.controller._read_json(self.workspace / "workflow" / "config.json") != self.config.to_dict():
            raise WorkflowCheckpointError("frozen stage configuration changed")
        master = self.controller.load_master()
        if master["plan_sha256"] != self._master_sha:
            raise WorkflowCheckpointError("validated master plan changed")
        return master

    def _build(self, *, resumed: bool) -> StagedRunResult:
        master = self._validated_master()
        build_prompt = self._prompt + "\n\nValidated build plan:\n" + json.dumps(
            {"plan": master["plan"], "expected_paths": master["expected_paths"]}, ensure_ascii=False,
        ) + "\nSave complete candidate files early, check public constraints and finish with _agent_summary.md."
        if resumed:
            build_prompt += "\nContinue this same attempt from the saved candidate and complete tool history; finish within the remaining aggregate budget."
        build_started = time.monotonic()
        rounds = 0

        def boundary(_diagnostics) -> bool:
            nonlocal rounds
            rounds += 1
            return (
                time.monotonic() - build_started >= self.config.policy.build_seconds
                or (self.config.policy.checkpoint_after_rounds is not None
                    and rounds >= self.config.policy.checkpoint_after_rounds)
            )

        try:
            result = self.agent.run(
                build_prompt, self.workspace, timeout=self._remaining(),
                usage_ledger=self.usage_ledger, tool_steps_offset=self._steps,
                stage_boundary=None if resumed else boundary,
            )
        except StageBoundary:
            self._steps = self.agent.last_tool_steps
            self._remaining()
            diagnostics = self.agent.last_invocation
            if resumed or not diagnostics.usage_complete or not diagnostics.transcript_complete:
                raise WorkflowCheckpointError("stage boundary cannot authorize resume") from None
            checkpoint = self._checkpoint("checkpointed")
            self._checkpoint_number, self._can_resume = checkpoint.number, True
            self._checkpoint_sha = checkpoint.checkpoint_sha256
            return StagedRunResult("checkpointed", checkpoint.number, False)
        # All other exceptions propagate. Neither an API error nor an exhausted ledger is a retry.
        self._steps = self.agent.last_tool_steps
        self._remaining()
        checkpoint = self._checkpoint("build_ready")
        return StagedRunResult("build_ready", checkpoint.number, resumed, result)

    def resume(self) -> StagedRunResult:
        if self._resumed or not self._can_resume or self._checkpoint_number is None:
            raise WorkflowCheckpointError("resume requires this process's single cooperative checkpoint")
        self._remaining()
        current = self.controller.state()
        if AggregateUsage.from_dict(current["usage"]) != self._usage(elapsed_ms=current["usage"]["elapsed_ms"]):
            raise WorkflowCheckpointError("live aggregate ledger changed after checkpoint")
        saved = self.controller.load_checkpoint(self._checkpoint_number)
        if saved.checkpoint_sha256 != self._checkpoint_sha:
            raise WorkflowCheckpointError("cooperative checkpoint changed")
        if saved.transcript is None or hashlib.sha256(self._build_transcript.read_bytes()).hexdigest() != saved.transcript["sha256"]:
            raise WorkflowCheckpointError("live transcript changed after checkpoint")
        self.controller.resume(self._checkpoint_number)
        self._can_resume, self._resumed = False, True
        self.controller.transition("build_running")
        return self._build(resumed=True)

    def _usage(self, *, elapsed_ms: int | None = None) -> AggregateUsage:
        if elapsed_ms is None:
            elapsed_ms = max(0, math.ceil((time.monotonic() - self._started) * 1000))
        snapshot = self.usage_ledger.snapshot
        return AggregateUsage(
            True, snapshot.input_tokens, snapshot.output_tokens, snapshot.total_tokens,
            snapshot.cost_micros, snapshot.rounds, self._steps, elapsed_ms,
        )

    def _checkpoint(self, stage: str):
        self.controller.assert_paths_safe()
        self._validated_master()
        paths = []
        for path in self._expected:
            target = self.workspace / path
            if target.exists() or target.is_symlink():
                paths.append(path)
            elif stage == "build_ready":
                raise WorkflowCheckpointError("build is missing a declared output")
        # Retain an immutable transcript per checkpoint; active history changes on resume.
        number = (self.controller.state()["checkpoint_number"] or 0) + 1
        transcript = self.workspace / "workflow" / f"transcript-{number:06d}.jsonl"
        if self._build_transcript.is_symlink():
            raise WorkflowCheckpointError("unsafe staged transcript")
        with transcript.open("xb") as stream:
            stream.write(self._build_transcript.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        return self.controller.checkpoint(
            stage=stage, declared_paths=paths, usage=self._usage(),
            transcript=transcript.relative_to(self.workspace),
        )


__all__ = ["StagePolicy", "StagedRunResult", "StagedWorkflowConfig", "StagedWorkflowRunner"]
