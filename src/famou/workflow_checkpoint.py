"""Durable, score-free control plane for the staged normal workflow.

This module deliberately owns only scheduling/checkpoint evidence.  It never creates or validates
subject receipts and never talks to a model or the private evaluator.  EffectTrialRunner remains
the authority for those operations.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

WORKFLOW_SCHEMA_VERSION = "1"
_MAX_JSON_BYTES = 512 * 1024
_MAX_PLAN_ITEMS = 64
_MAX_PLAN_ITEM_BYTES = 2_048
_MAX_PATHS = 128
_MAX_PATH_BYTES = 1_024
_HASH_CHUNK_BYTES = 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|(?:api[_-]?key|password|token)\s*[:=]\s*[^\s,;]+)")
_FORBIDDEN = re.compile(r"(?i)(?:baseline|private|evaluator|harness|score|credential)")
_STAGES = (
    "created", "master_running", "master_ready", "build_running", "checkpointed",
    "resuming", "build_ready", "harness_pending", "terminal",
)
_NEXT = {
    "created": {"master_running"},
    "master_running": {"master_ready"},
    "master_ready": {"build_running"},
    "build_running": {"checkpointed", "build_ready"},
    "checkpointed": {"resuming", "build_ready"},
    "resuming": {"build_running", "build_ready"},
    "build_ready": {"harness_pending", "terminal"},
    "harness_pending": {"terminal"},
    "terminal": set(),
}


class WorkflowCheckpointError(ValueError):
    """Malformed or invalid workflow control-plane evidence."""


def _fail(message: str) -> None:
    raise WorkflowCheckpointError(message)


def _strict_dict(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    keys = set(value)
    if keys != required:
        missing = required - keys
        extra = keys - required
        detail = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unsupported " + ", ".join(sorted(extra)))
        _fail(f"{label} has invalid fields ({'; '.join(detail)})")
    return value


def _text(value: object, label: str, *, identifier: bool = False, max_bytes: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > max_bytes or "\x00" in value:
        _fail(f"{label} must be bounded text")
    if identifier and _ID.fullmatch(value) is None:
        _fail(f"{label} must be a safe identifier")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _relpath(value: object, label: str = "path") -> str:
    text = _text(value, label, max_bytes=_MAX_PATH_BYTES)
    path = Path(text)
    if (
        "\\" in text or path.is_absolute() or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or text != path.as_posix()
    ):
        _fail(f"{label} must be a confined POSIX relative path")
    return path.as_posix()


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _canonical(value: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError("workflow payload is not JSON serializable") from exc
    raw = (encoded + "\n").encode("utf-8")
    if len(raw) > _MAX_JSON_BYTES:
        _fail("workflow payload exceeds its bounded size")
    return raw


def _sha_payload(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _redact(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)


@dataclass(frozen=True)
class WorkflowManifest:
    run_id: str
    attempt_id: str
    source_sha256: str
    suite_key: str
    case_key: str
    request_sha256: str
    model_profile_sha256: str | None
    ceilings: Mapping[str, int | float | None]

    def __post_init__(self) -> None:
        for name in ("run_id", "attempt_id", "suite_key", "case_key"):
            _text(getattr(self, name), name, identifier=True)
        for name in ("source_sha256", "request_sha256"):
            _digest(getattr(self, name), name)
        if self.model_profile_sha256 is not None:
            _digest(self.model_profile_sha256, "model_profile_sha256")
        if not isinstance(self.ceilings, Mapping):
            _fail("ceilings must be an object")
        ceilings = dict(self.ceilings)
        if set(ceilings) != {"max_wall_seconds", "max_tool_steps", "max_total_tokens", "max_cost_micros"}:
            _fail("ceilings must contain exactly the four aggregate limits")
        wall = ceilings["max_wall_seconds"]
        if isinstance(wall, bool) or not isinstance(wall, (int, float)) or not math.isfinite(float(wall)) or wall <= 0:
            _fail("max_wall_seconds must be finite and positive")
        for key in ("max_tool_steps", "max_total_tokens"):
            _integer(ceilings[key], key, 1)
        cost = ceilings["max_cost_micros"]
        if cost is not None:
            _integer(cost, "max_cost_micros", 1)
        object.__setattr__(self, "ceilings", MappingProxyType(ceilings))

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id, "attempt_id": self.attempt_id,
            "source_sha256": self.source_sha256, "suite_key": self.suite_key,
            "case_key": self.case_key, "request_sha256": self.request_sha256,
            "model_profile_sha256": self.model_profile_sha256,
            "ceilings": dict(self.ceilings),
        }

    @classmethod
    def from_dict(cls, value: object) -> WorkflowManifest:
        obj = _strict_dict(value, {"run_id", "attempt_id", "source_sha256", "suite_key", "case_key", "request_sha256", "model_profile_sha256", "ceilings"}, "manifest")
        ceilings = obj["ceilings"]
        if not isinstance(ceilings, dict):
            _fail("ceilings must be an object")
        return cls(
            run_id=obj["run_id"], attempt_id=obj["attempt_id"], source_sha256=obj["source_sha256"],
            suite_key=obj["suite_key"], case_key=obj["case_key"], request_sha256=obj["request_sha256"],
            model_profile_sha256=obj["model_profile_sha256"], ceilings=dict(ceilings),
        )


@dataclass(frozen=True)
class AggregateUsage:
    """One cumulative ledger shared by master, build, and resume."""

    available: bool
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_micros: int | None
    rounds: int
    tool_steps: int
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            _fail("usage.available must be boolean")
        for key in ("input_tokens", "output_tokens", "total_tokens", "cost_micros"):
            value = getattr(self, key)
            if value is not None:
                _integer(value, f"usage.{key}")
        _integer(self.rounds, "usage.rounds")
        _integer(self.tool_steps, "usage.tool_steps")
        _integer(self.elapsed_ms, "usage.elapsed_ms")
        if self.available:
            if any(getattr(self, key) is None for key in ("input_tokens", "output_tokens", "total_tokens")):
                _fail("available usage requires token counters")
            if self.input_tokens + self.output_tokens != self.total_tokens:  # type: ignore[operator]
                _fail("usage total must equal input plus output")
        elif any(getattr(self, key) is not None for key in ("input_tokens", "output_tokens", "total_tokens", "cost_micros")):
            _fail("unavailable usage must not claim counters")

    @classmethod
    def unavailable(
        cls, *, rounds: int = 0, tool_steps: int = 0, elapsed_ms: int = 0
    ) -> AggregateUsage:
        return cls(False, None, None, None, None, rounds, tool_steps, elapsed_ms)

    @classmethod
    def zero(cls) -> AggregateUsage:
        return cls(True, 0, 0, 0, 0, 0, 0, 0)

    def to_dict(self) -> dict[str, object]:
        return {"available": self.available, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "total_tokens": self.total_tokens, "cost_micros": self.cost_micros, "rounds": self.rounds, "tool_steps": self.tool_steps, "elapsed_ms": self.elapsed_ms}

    @classmethod
    def from_dict(cls, value: object) -> AggregateUsage:
        obj = _strict_dict(value, {"available", "input_tokens", "output_tokens", "total_tokens", "cost_micros", "rounds", "tool_steps", "elapsed_ms"}, "usage")
        return cls(obj["available"], obj["input_tokens"], obj["output_tokens"], obj["total_tokens"], obj["cost_micros"], obj["rounds"], obj["tool_steps"], obj["elapsed_ms"])

    def monotonic_from(self, previous: AggregateUsage) -> bool:
        if self.tool_steps < previous.tool_steps or self.rounds < previous.rounds or self.elapsed_ms < previous.elapsed_ms:
            return False
        if not self.available:
            return not previous.available
        if not previous.available:
            # Only the untouched initial state can acquire its first observed ledger. Once a
            # round/tool was unaccounted for, later samples cannot establish its missing usage.
            return previous.rounds == 0 and previous.tool_steps == 0 and previous.elapsed_ms == 0
        token_monotonic = all(
            getattr(self, key) is not None and getattr(previous, key) is not None
            and getattr(self, key) >= getattr(previous, key)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        if not token_monotonic:
            return False
        return not (
            previous.cost_micros is not None
            and (self.cost_micros is None or self.cost_micros < previous.cost_micros)
        )


@dataclass(frozen=True)
class Checkpoint:
    number: int
    stage: str
    prior_stage: str
    usage: AggregateUsage
    declared_paths: tuple[dict[str, object], ...]
    transcript: dict[str, object] | None
    checkpoint_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": WORKFLOW_SCHEMA_VERSION, "kind": "workflow_checkpoint",
            "number": self.number, "stage": self.stage, "prior_stage": self.prior_stage,
            "usage": self.usage.to_dict(), "declared_paths": [dict(x) for x in self.declared_paths],
            "transcript": self.transcript, "checkpoint_sha256": self.checkpoint_sha256,
        }


class WorkflowController:
    """Validate and persist master/checkpoint/state records for one logical attempt."""

    def __init__(self, workspace: str | Path, manifest: WorkflowManifest | Mapping[str, object]):
        self.workspace = Path(workspace).expanduser().absolute()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.workspace.is_symlink():
            _fail("workspace must not be a symlink")
        self.workspace = self.workspace.resolve(strict=True)
        self.manifest = manifest if isinstance(manifest, WorkflowManifest) else WorkflowManifest.from_dict(manifest)
        self.workflow = self.workspace / "workflow"
        if self.workflow.is_symlink() or (self.workflow.exists() and not self.workflow.is_dir()):
            _fail("workflow path must be a regular directory")
        self.workflow.mkdir(exist_ok=True)
        self.checkpoints = self.workflow / "checkpoints"
        if self.checkpoints.is_symlink() or (self.checkpoints.exists() and not self.checkpoints.is_dir()):
            _fail("workflow checkpoints path must be a regular directory")
        self.checkpoints.mkdir(exist_ok=True)
        self.assert_paths_safe()
        if not (self.workflow / "state.json").exists():
            # At creation no provider usage has been observed.  Keep that fact explicit instead
            # of manufacturing a zero ledger which could make an unavailable sample look free.
            self._write_replace(self.workflow / "state.json", self._state_payload("created", None, False, AggregateUsage.unavailable()))
        else:
            self._validate_state(self._read_json(self.workflow / "state.json"))
            self._recover_orphan_checkpoint()

    def assert_paths_safe(self) -> None:
        """Reject replaced control directories before subsequent filesystem operations.

        The subject shares the filesystem, so construction-time validation is insufficient.
        These checks detect static replacement; they are not a concurrent hostile-writer sandbox.
        """
        try:
            if (
                self.workspace.is_symlink() or not self.workspace.is_dir()
                or self.workspace.resolve(strict=True) != self.workspace
            ):
                _fail("workflow workspace must remain a canonical directory without symlinks")
            for path in (self.workflow, self.checkpoints):
                relative = path.relative_to(self.workspace)
                current = self.workspace
                for part in relative.parts:
                    if part in {"", ".", ".."}:
                        _fail("workflow directory escapes workspace")
                    current = current / part
                    if current.is_symlink() or not current.is_dir():
                        _fail("workflow directories must remain regular directories without symlinks")
        except WorkflowCheckpointError:
            raise
        except (OSError, ValueError) as exc:
            raise WorkflowCheckpointError("workflow directories are not safely confined") from exc

    def _assert_record_path_safe(self, path: Path) -> None:
        self.assert_paths_safe()
        try:
            relative = path.relative_to(self.workspace)
        except ValueError as exc:
            raise WorkflowCheckpointError("workflow record escapes workspace") from exc
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            _fail("workflow record must be a confined file path")
        current = self.workspace
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                _fail("workflow record parents must be regular directories without symlinks")

    def _recover_orphan_checkpoint(self) -> None:
        """Complete a checkpoint whose state replacement was interrupted."""
        current = self.state()
        current_number = current["checkpoint_number"] or 0
        candidates = sorted(
            int(path.stem)
            for path in self.checkpoints.glob("[0-9]" * 6 + ".json")
            if path.is_file() and not path.is_symlink()
        )
        if not candidates or candidates[-1] <= current_number:
            return
        if candidates[-1] != current_number + 1 or len(candidates) != current_number + 1:
            _fail("workflow checkpoint sequence is inconsistent")
        checkpoint = self.load_checkpoint(candidates[-1])
        if checkpoint.prior_stage != current["stage"]:
            _fail("orphan workflow checkpoint has an invalid prior stage")
        if not checkpoint.usage.monotonic_from(AggregateUsage.from_dict(current["usage"])):
            _fail("orphan checkpoint usage moved backwards or reset")
        self._write_replace(
            self.workflow / "state.json",
            self._state_payload(
                checkpoint.stage,
                checkpoint.number,
                current["resume_used"],
                checkpoint.usage,
            ),
        )

    def _state_payload(self, stage: str, checkpoint_number: int | None, resume_used: bool, usage: AggregateUsage) -> dict[str, object]:
        return {"schema_version": WORKFLOW_SCHEMA_VERSION, "kind": "workflow_state", **self.manifest.to_dict(), "stage": stage, "checkpoint_number": checkpoint_number, "resume_used": resume_used, "usage": usage.to_dict()}

    def _read_json(self, path: Path) -> dict[str, object]:
        self._assert_record_path_safe(path)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
                _fail("workflow record is not a bounded regular file")
            value = json.loads(path.read_text(encoding="utf-8"))
        except WorkflowCheckpointError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkflowCheckpointError("invalid workflow JSON") from exc
        if not isinstance(value, dict):
            _fail("workflow record must be an object")
        return value

    def _write_replace(self, destination: Path, value: Mapping[str, object]) -> None:
        self._assert_record_path_safe(destination)
        raw = _canonical(value)
        if destination.is_symlink():
            _fail("workflow destination must not be a symlink")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        created = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created = True
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if created:
                temporary.unlink(missing_ok=True)

    def _write_new(self, destination: Path, value: Mapping[str, object]) -> None:
        self._assert_record_path_safe(destination)
        raw = _canonical(value)
        if destination.exists() or destination.is_symlink():
            _fail("workflow checkpoint already exists")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        created = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created = True
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise WorkflowCheckpointError("workflow checkpoint already exists") from exc
        finally:
            if created:
                temporary.unlink(missing_ok=True)

    def state(self) -> dict[str, object]:
        value = self._read_json(self.workflow / "state.json")
        self._validate_state(value)
        return value

    def _validate_state(self, value: Mapping[str, object]) -> None:
        required = set(self.manifest.to_dict()) | {"schema_version", "kind", "stage", "checkpoint_number", "resume_used", "usage"}
        obj = _strict_dict(value, required, "workflow state")
        if obj["schema_version"] != WORKFLOW_SCHEMA_VERSION or obj["kind"] != "workflow_state":
            _fail("invalid workflow state identity")
        self._validate_binding(obj)
        if obj["stage"] not in _STAGES:
            _fail("invalid workflow state stage")
        if obj["checkpoint_number"] is not None:
            _integer(obj["checkpoint_number"], "checkpoint_number", 1)
        if type(obj["resume_used"]) is not bool:
            _fail("resume_used must be boolean")
        self._validate_usage(AggregateUsage.from_dict(obj["usage"]))
        if obj["stage"] in {"checkpointed", "resuming"} and obj["checkpoint_number"] is None:
            _fail("workflow stage requires a checkpoint")
        if obj["stage"] == "resuming" and not obj["resume_used"]:
            _fail("resuming state requires a consumed resume guard")

    def _validate_binding(self, obj: Mapping[str, object]) -> None:
        expected = self.manifest.to_dict()
        for key, value in expected.items():
            if obj.get(key) != value:
                _fail(f"workflow binding mismatch: {key}")

    def transition(self, stage: str) -> None:
        _text(stage, "stage", identifier=True)
        if stage not in _STAGES:
            _fail("invalid workflow stage")
        if stage == "harness_pending":
            _fail("harness authority belongs to EffectTrialRunner")
        if stage == "resuming":
            _fail("resuming transition requires resume() and its one-resume guard")
        if stage == "checkpointed":
            _fail("checkpointed transition requires a durable checkpoint()")
        current = self.state()
        old = current["stage"]
        if stage == old:
            _fail(f"duplicate workflow transition: {stage}")
        if stage not in _NEXT[old]:
            _fail(f"out-of-order workflow transition: {old} -> {stage}")
        self._write_replace(self.workflow / "state.json", self._state_payload(stage, current["checkpoint_number"], current["resume_used"], AggregateUsage.from_dict(current["usage"])))

    def record_usage(self, usage: AggregateUsage | Mapping[str, object]) -> None:
        """Persist the master's observed ledger even when its plan cannot be accepted."""
        current = self.state()
        if current["stage"] not in {"master_running", "master_ready"}:
            _fail("master usage may only be recorded during the master stage")
        snapshot = usage if isinstance(usage, AggregateUsage) else AggregateUsage.from_dict(usage)
        if not snapshot.monotonic_from(AggregateUsage.from_dict(current["usage"])):
            _fail("usage ledger moved backwards or reset")
        self._validate_usage(snapshot)
        self._write_replace(
            self.workflow / "state.json",
            self._state_payload(current["stage"], current["checkpoint_number"], current["resume_used"], snapshot),
        )

    def write_master(self, plan: Sequence[str], expected_paths: Sequence[str]) -> dict[str, object]:
        current = self.state()
        if current["stage"] not in {"created", "master_running"}:
            _fail("master checkpoint is no longer writable")
        if current["stage"] == "created":
            self.transition("master_running")
        if not isinstance(plan, Sequence) or isinstance(plan, (str, bytes)) or not 1 <= len(plan) <= _MAX_PLAN_ITEMS:
            _fail("plan must be a bounded non-empty sequence")
        normalized_plan: list[str] = []
        for item in plan:
            text = _redact(_text(item, "plan item", max_bytes=_MAX_PLAN_ITEM_BYTES))
            if _FORBIDDEN.search(text):
                _fail("master plan contains forbidden evaluator evidence")
            normalized_plan.append(text)
        if not isinstance(expected_paths, Sequence) or isinstance(expected_paths, (str, bytes)) or len(expected_paths) > _MAX_PATHS:
            _fail("expected_paths must be a bounded sequence")
        paths = [_relpath(item, "expected path") for item in expected_paths]
        if len(set(paths)) != len(paths):
            _fail("expected paths must be unique")
        if any(_FORBIDDEN.search(path) for path in paths):
            _fail("expected paths contain forbidden evaluator evidence")
        payload = {"schema_version": WORKFLOW_SCHEMA_VERSION, "kind": "workflow_master", **self.manifest.to_dict(), "plan": normalized_plan, "expected_paths": paths}
        payload["plan_sha256"] = _sha_payload({k: payload[k] for k in payload if k != "plan_sha256"})
        self._write_replace(self.workflow / "master.json", payload)
        self.transition("master_ready")
        return payload

    def load_master(self) -> dict[str, object]:
        """Load and validate the score-free master projection."""
        value = self._read_json(self.workflow / "master.json")
        required = set(self.manifest.to_dict()) | {
            "schema_version", "kind", "plan", "expected_paths", "plan_sha256",
        }
        obj = _strict_dict(value, required, "workflow master")
        if obj["schema_version"] != WORKFLOW_SCHEMA_VERSION or obj["kind"] != "workflow_master":
            _fail("invalid workflow master identity")
        self._validate_binding(obj)
        plan = obj["plan"]
        if not isinstance(plan, list) or not 1 <= len(plan) <= _MAX_PLAN_ITEMS:
            _fail("invalid master plan")
        for item in plan:
            original = _text(item, "plan item", max_bytes=_MAX_PLAN_ITEM_BYTES)
            text = _redact(original)
            if text != original:
                _fail("master plan contains a credential")
            if _FORBIDDEN.search(text):
                _fail("master plan contains forbidden evaluator evidence")
        expected = obj["expected_paths"]
        if not isinstance(expected, list) or len(expected) > _MAX_PATHS:
            _fail("invalid expected paths")
        normalized = [_relpath(item, "expected path") for item in expected]
        if normalized != expected or len(set(normalized)) != len(normalized):
            _fail("invalid expected paths")
        if any(_FORBIDDEN.search(path) for path in normalized):
            _fail("expected paths contain forbidden evaluator evidence")
        if _digest(obj["plan_sha256"], "plan_sha256") != _sha_payload({k: obj[k] for k in obj if k != "plan_sha256"}):
            _fail("master plan digest mismatch")
        return obj

    def _path_record(self, relative: str) -> dict[str, object]:
        relative = _relpath(relative)
        path = self.workspace / relative
        # Resolve only for containment; reject symlinks in every existing component first.
        current = self.workspace
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                _fail("declared path must not contain a symlink")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.workspace.resolve())
        except (OSError, ValueError) as exc:
            raise WorkflowCheckpointError("declared path escapes workspace") from exc
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            _fail("declared path must be a regular file")
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(_HASH_CHUNK_BYTES):
                    size += len(chunk)
                    digest.update(chunk)
        except OSError as exc:
            raise WorkflowCheckpointError("declared path cannot be read") from exc
        return {"path": relative, "size_bytes": size, "sha256": digest.hexdigest()}

    def _transcript_record(self, transcript: str | Path | None) -> dict[str, object] | None:
        if transcript is None:
            return None
        relative = _relpath(transcript.as_posix() if isinstance(transcript, Path) else transcript, "transcript path")
        return self._path_record(relative)

    def _validate_usage(self, usage: AggregateUsage) -> None:
        ceilings = self.manifest.ceilings
        if usage.available and usage.total_tokens is not None and usage.total_tokens > ceilings["max_total_tokens"]:
            _fail("aggregate token ceiling exceeded")
        if usage.available and usage.cost_micros is not None and ceilings["max_cost_micros"] is not None and usage.cost_micros > ceilings["max_cost_micros"]:
            _fail("aggregate cost ceiling exceeded")
        if usage.tool_steps > ceilings["max_tool_steps"]:
            _fail("aggregate tool-step ceiling exceeded")
        if usage.elapsed_ms > float(ceilings["max_wall_seconds"]) * 1000:
            _fail("aggregate wall-time ceiling exceeded")

    def checkpoint(self, *, stage: str, declared_paths: Sequence[str], usage: AggregateUsage | Mapping[str, object], transcript: str | Path | None = None) -> Checkpoint:
        current = self.state()
        if current["stage"] not in {"build_running", "resuming", "checkpointed"}:
            _fail("checkpoint is not allowed in the current stage")
        if stage not in {"checkpointed", "build_ready"}:
            _fail("checkpoint stage must be checkpointed or build_ready")
        if not isinstance(declared_paths, Sequence) or isinstance(declared_paths, (str, bytes)) or len(declared_paths) > _MAX_PATHS:
            _fail("declared_paths must be a bounded sequence")
        records = tuple(self._path_record(path) for path in declared_paths)
        if len({x["path"] for x in records}) != len(records):
            _fail("declared paths must be unique")
        snapshot = usage if isinstance(usage, AggregateUsage) else AggregateUsage.from_dict(usage)
        previous = AggregateUsage.from_dict(current["usage"])
        if not snapshot.monotonic_from(previous):
            _fail("usage ledger moved backwards or reset")
        self._validate_usage(snapshot)
        number = (current["checkpoint_number"] or 0) + 1
        prior_stage = current["stage"]
        transcript_record = self._transcript_record(transcript)
        body: dict[str, object] = {"schema_version": WORKFLOW_SCHEMA_VERSION, "kind": "workflow_checkpoint", **self.manifest.to_dict(), "number": number, "stage": stage, "prior_stage": prior_stage, "usage": snapshot.to_dict(), "declared_paths": list(records), "transcript": transcript_record}
        digest = _sha_payload(body)
        body["checkpoint_sha256"] = digest
        self._write_new(self.checkpoints / f"{number:06d}.json", body)
        self._write_replace(self.workflow / "state.json", self._state_payload(stage, number, current["resume_used"], snapshot))
        return Checkpoint(number, stage, prior_stage, snapshot, records, transcript_record, digest)

    def resume(self, checkpoint_number: int | None = None) -> Checkpoint:
        current = self.state()
        if current["resume_used"]:
            _fail("workflow resume is allowed only once")
        if current["stage"] != "checkpointed":
            _fail("resume requires a checkpointed stage")
        number = current["checkpoint_number"]
        if checkpoint_number is not None:
            _integer(checkpoint_number, "checkpoint number", 1)
        if checkpoint_number is not None and checkpoint_number != number:
            _fail("resume checkpoint does not match current state")
        if not isinstance(number, int):
            _fail("resume requires a checkpoint")
        self.load_master()
        checkpoint = self.load_checkpoint(number)
        if checkpoint.stage != current["stage"] or checkpoint.usage != AggregateUsage.from_dict(current["usage"]):
            _fail("resume checkpoint does not match current state")
        if not checkpoint.usage.available:
            _fail("unavailable usage cannot authorize resume")
        usage = checkpoint.usage
        ceilings = self.manifest.ceilings
        for used, maximum, label in (
            (usage.total_tokens, ceilings["max_total_tokens"], "token"),
            (usage.tool_steps, ceilings["max_tool_steps"], "tool-step"),
            (usage.elapsed_ms, float(ceilings["max_wall_seconds"]) * 1000, "wall-time"),
            (usage.cost_micros, ceilings["max_cost_micros"], "cost"),
        ):
            if maximum is not None and (used is None or used >= maximum):
                _fail(f"resume requires known headroom below the aggregate {label} ceiling")
        self._write_replace(self.workflow / "state.json", self._state_payload("resuming", number, True, checkpoint.usage))
        return checkpoint

    def load_checkpoint(self, number: int) -> Checkpoint:
        _integer(number, "checkpoint number", 1)
        value = self._read_json(self.checkpoints / f"{number:06d}.json")
        required = set(self.manifest.to_dict()) | {"schema_version", "kind", "number", "stage", "prior_stage", "usage", "declared_paths", "transcript", "checkpoint_sha256"}
        obj = _strict_dict(value, required, "workflow checkpoint")
        if obj["schema_version"] != WORKFLOW_SCHEMA_VERSION or obj["kind"] != "workflow_checkpoint" or obj["number"] != number:
            _fail("invalid checkpoint identity")
        self._validate_binding(obj)
        _integer(obj["number"], "checkpoint number", 1)
        if obj["stage"] not in {"checkpointed", "build_ready"} or obj["prior_stage"] not in {"build_running", "resuming", "checkpointed"}:
            _fail("invalid checkpoint stage")
        usage = AggregateUsage.from_dict(obj["usage"])
        self._validate_usage(usage)
        records = obj["declared_paths"]
        if not isinstance(records, list) or len(records) > _MAX_PATHS:
            _fail("invalid checkpoint paths")
        normalized: list[dict[str, object]] = []
        for item in records:
            record = _strict_dict(item, {"path", "size_bytes", "sha256"}, "declared path record")
            path_record = self._path_record(record["path"])
            if record != path_record:
                _fail("declared path digest changed")
            normalized.append(record)
        if len({record["path"] for record in normalized}) != len(normalized):
            _fail("declared paths must be unique")
        transcript = obj["transcript"]
        if transcript is not None:
            record = _strict_dict(transcript, {"path", "size_bytes", "sha256"}, "transcript record")
            if record != self._path_record(record["path"]):
                _fail("transcript digest changed")
        digest = obj["checkpoint_sha256"]
        if _digest(digest, "checkpoint_sha256") != _sha_payload({k: obj[k] for k in obj if k != "checkpoint_sha256"}):
            _fail("checkpoint digest mismatch")
        return Checkpoint(number, obj["stage"], obj["prior_stage"], usage, tuple(normalized), transcript, digest)

    def mark_build_ready(self) -> None:
        current = self.state()
        if current["stage"] == "checkpointed":
            _fail("build ready requires resume or an explicit checkpoint")
        self.transition("build_ready")

    def mark_harness_pending(self) -> None:
        self.transition("harness_pending")

    def terminal(self) -> None:
        self.transition("terminal")


# Short aliases make the control-plane seam convenient to import without exposing evaluator APIs.
WorkflowState = WorkflowController
WorkflowError = WorkflowCheckpointError
WorkflowCheckpoint = Checkpoint
