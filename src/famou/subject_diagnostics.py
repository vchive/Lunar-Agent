"""Bounded, non-authoritative failure claims; never a source of scores or receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError

from .agent_loop import AgentInputRequired
from .runtime import RuntimeExecutionError

MAX_DIAGNOSTIC_BYTES = 4096
MAX_COUNTER = 1_000_000
_STAGES = {"runtime", "model", "tool", "public_projection", "receipt"}
_CODES = {
    "runtime_failed", "model_failed", "model_http_failed", "tool_failed", "step_limit",
    "timeout", "input_required", "budget_exceeded", "usage_invalid",
    "frozen_request_changed", "public_file_set_changed", "public_file_changed",
    "public_symlink", "public_projection_failed", "receipt_invalid",
}
_FIELDS = {
    "schema_version", "kind", "mode", "request_sha256", "run_index", "round_index",
    "stage", "code", "model_turns", "tool_steps", "http_status",
}


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def normalize_diagnostic(value: object) -> dict[str, object]:
    """Accept only the fixed score-free vocabulary, without arbitrary error strings."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("invalid diagnostic fields")
    if value["schema_version"] != "1" or value["kind"] != "subject_failure":
        raise ValueError("invalid diagnostic version or kind")
    if value["mode"] not in {"normal", "deep_evolution"}:
        raise ValueError("invalid diagnostic mode")
    digest = value["request_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid diagnostic digest")
    if not _integer(value["run_index"], 1, 1_000_000):
        raise ValueError("invalid diagnostic run")
    if value["mode"] == "normal":
        if value["round_index"] is not None:
            raise ValueError("normal diagnostic must not have a round")
    elif not _integer(value["round_index"], 1, 1000):
        raise ValueError("invalid diagnostic round")
    if value["stage"] not in _STAGES or value["code"] not in _CODES:
        raise ValueError("invalid diagnostic classification")
    if any(not _integer(value[key], 0, MAX_COUNTER) for key in ("model_turns", "tool_steps")):
        raise ValueError("invalid diagnostic counters")
    if value["http_status"] is not None and not _integer(value["http_status"], 100, 599):
        raise ValueError("invalid diagnostic HTTP status")
    return dict(value)


def _relative_parts(relative: str) -> list[str]:
    if not isinstance(relative, str) or len(relative.encode("utf-8")) > 1024:
        raise ValueError("invalid diagnostic path")
    parts = relative.split("/")
    if "\\" in relative or "\x00" in relative or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid diagnostic path")
    return parts


def _parent_fd(root: Path, relative: str, *, create: bool = False) -> tuple[int, str]:
    """Walk from / with directory descriptors, refusing every symlink component."""
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("diagnostic root must be absolute")
    parts = _relative_parts(relative)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    try:
        root_parts = list(root.parts[1:])
        for index, part in enumerate(root_parts + parts[:-1]):
            if create and index >= len(root_parts):
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def read_bounded_file(root: Path, relative: str, maximum: int = MAX_DIAGNOSTIC_BYTES) -> bytes:
    parent, name = _parent_fd(root, relative)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
                raise ValueError("diagnostic input must be a bounded regular file")
            content = stream.read(maximum + 1)
            if not content or len(content) > maximum:
                raise ValueError("diagnostic input exceeds its bounded size")
            return content
    finally:
        os.close(parent)


def publish_diagnostic(root: Path, relative: str, diagnostic: object) -> None:
    payload = normalize_diagnostic(diagnostic)
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(content) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("diagnostic exceeds its bounded size")
    parent, name = _parent_fd(root, relative, create=True)
    temporary = ".subject-diagnostic-" + secrets.token_hex(12)
    created = False
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=parent,
        )
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Linking rather than replacing also rejects every preexisting destination type.
        os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)


@dataclass(frozen=True)
class SubjectDiagnosticContext:
    workspace: Path
    sidecar: str
    mode: str
    request_sha256: str
    run_index: int
    round_index: int | None

    @classmethod
    def from_request(
        cls, workspace: Path, request: Mapping[str, object], request_sha256: str,
    ) -> SubjectDiagnosticContext:
        receipt = request["receipt_path"]
        _relative_parts(receipt)  # type: ignore[arg-type]
        context = cls(
            workspace, Path(receipt).with_suffix(".failure.json").as_posix(),  # type: ignore[arg-type]
            request["mode"], request_sha256, request["run_index"],  # type: ignore[arg-type]
            request.get("round_index"),  # type: ignore[arg-type]
        )
        normalize_diagnostic(context.payload("runtime", "runtime_failed", 0, 0, None))
        return context

    def payload(
        self, stage: str, code: str, model_turns: int, tool_steps: int, http_status: int | None,
    ) -> dict[str, object]:
        return {
            "schema_version": "1", "kind": "subject_failure", "mode": self.mode,
            "request_sha256": self.request_sha256, "run_index": self.run_index,
            "round_index": self.round_index, "stage": stage, "code": code,
            "model_turns": model_turns, "tool_steps": tool_steps, "http_status": http_status,
        }

    def emit(self, diagnostic: object) -> None:
        try:
            publish_diagnostic(self.workspace, self.sidecar, diagnostic)
        except Exception:  # noqa: BLE001 - diagnostics must not mask execution failures
            # Diagnostics must never mask the original subject failure.
            return

    def collect(self) -> None:
        try:
            raw = read_bounded_file(self.workspace, self.sidecar)
            payload = normalize_diagnostic(json.loads(raw))
            for key in ("mode", "request_sha256", "run_index", "round_index"):
                if payload[key] != getattr(self, key):
                    return
            name = "subject-failure.json" if self.round_index is None else f"subject-{self.round_index:03d}-failure.json"
            publish_diagnostic(self.workspace.parent, "diagnostics/" + name, payload)
        except Exception:  # noqa: BLE001 - malformed or unavailable evidence is non-authoritative
            # Subject claims cannot affect runner error, score, or recovery authority.
            return


def capture_subject_diagnostic_context(workspace: Path, request_name: str) -> SubjectDiagnosticContext | None:
    try:
        raw = read_bounded_file(workspace, request_name, 2 * 1024 * 1024)
        context = SubjectDiagnosticContext.from_request(workspace, json.loads(raw), hashlib.sha256(raw).hexdigest())
        # An existing same-round sidecar is old evidence, not a new invocation's diagnostic.
        try:
            parent, name = _parent_fd(workspace, context.sidecar)
        except FileNotFoundError:
            return context
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return context
        finally:
            os.close(parent)
    except Exception:  # noqa: BLE001 - diagnostic setup cannot change process behavior
        return None
    return None


class SubjectDiagnosticObserver:
    """Project only fixed event types and integer counts; discard event bodies."""

    def __init__(self) -> None:
        self.stage = "runtime"
        self.code = "runtime_failed"
        self.model_turns = 0
        self.tool_steps = 0

    def event(self, kind: str, payload: dict[str, object]) -> None:
        if kind == "agent_model_turn" and _integer(payload.get("turn"), 0, MAX_COUNTER):
            self.model_turns = int(payload["turn"])  # type: ignore[arg-type]
        elif kind == "agent_tool_result":
            self.tool_steps = min(MAX_COUNTER, self.tool_steps + 1)
        elif kind == "agent_step_limit_reached":
            self.stage, self.code = "runtime", "step_limit"
        elif kind == "agent_runtime_failure":
            phase = payload.get("phase")
            if phase == "model_turn":
                self.stage, self.code = "model", "model_failed"
            elif phase == "tool":
                self.stage, self.code = "tool", "tool_failed"

    def emit_failure(
        self, context: SubjectDiagnosticContext, error: Exception, *, code: str | None = None,
    ) -> None:
        try:
            context.emit(self.failure(context, error, code=code))
        except Exception:  # noqa: BLE001 - classification must not mask the original exception
            return

    def failure(
        self, context: SubjectDiagnosticContext, error: Exception, *, code: str | None = None,
    ) -> dict[str, object]:
        http_status = None
        current: BaseException | None = error
        seen: set[int] = set()
        for _ in range(8):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            if isinstance(current, HTTPError) and _integer(current.code, 100, 599):
                http_status = current.code
                if self.stage == "model":
                    code = "model_http_failed"
                break
            if isinstance(current, TimeoutError) and self.stage in {"model", "runtime", "tool"}:
                code = "timeout"
            if isinstance(current, AgentInputRequired):
                code = "input_required"
            elif type(current) is RuntimeExecutionError and self.stage == "runtime":
                # Match only repository-owned fixed messages, never provider/model prose.
                message = str(current)
                if message == "agent loop timed out before the next model turn":
                    code = "timeout"
                elif message in {
                    "model profile usage is required for token/cost ceilings",
                    "model profile usage is invalid",
                }:
                    code = "usage_invalid"
                elif message in {
                    f"model profile budget {state}: {limit}"
                    for state in ("exceeded", "exhausted")
                    for limit in ("max_total_tokens", "max_cost_micros")
                }:
                    code = "budget_exceeded"
            current = current.__cause__
        return context.payload(
            self.stage, code or self.code, self.model_turns, self.tool_steps, http_status,
        )
