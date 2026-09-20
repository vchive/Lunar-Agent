"""Bound provider accounting and native-stage observation for Feature 139.

One high-level candidate ``AgentRequest`` may issue multiple model turns.  The
observer therefore binds every nested exchange to the request's native
run/task/budget identity instead of inferring candidate ownership from a
global ordinal. Preparation calls are bound at their native compiler/auditor
entry points. Unknown callers remain explicitly unbound.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import famou.runtime as runtime_module
from famou import evaluator_bundle as evaluator_bundle_module
from famou.agents import AgentRequest, RuntimeAgentAdapter
from famou.conversational import RuntimeContractCompiler
from famou.http_transport import (
    TransportFailure,
    TransportObservation,
    normalize_transport_observation,
)
from famou.runtime import _SECRET_RE, ModelRequestFailure, ModelTurn


def _load_shared_runtime():
    path = (Path(__file__).resolve().parents[3]
            / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py")
    name = "_lunar_measurement139_frozen113_runtime_guard"
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path:
            raise RuntimeError("shared_runtime_identity_mismatch")
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


_shared = _load_shared_runtime()
BaseRuntimeGuard = _shared.RuntimeGuard
ProviderConfiguration = _shared.ProviderConfiguration
MeasurementRuntimeError = _shared.MeasurementRuntimeError
load_provider = _shared.load_provider
MAX_PREFIX_BYTES = 64 * 1024
_ROLES = {"system", "user", "assistant", "tool"}
_PHASES = {"open_response", "read_response_body", "read_http_error_body"}
_REASONS = {"http_error", "transport_timeout", "transport_error"}
_STAGES = {"contract_compiler", "evaluator_compiler", "evaluator_auditor", "candidate_generation"}
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


def _clock():
    try:
        value = time.monotonic()
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except Exception:  # noqa: BLE001 - an optional clock must not prevent a request
        return None


def _elapsed(started, ended):
    if started is None or ended is None or ended < started:
        return None
    value = math.floor((ended - started) * 1000)
    return value if 0 <= value <= 10**12 else None


def _safe_token(value):
    return value if type(value) is str and _TOKEN.fullmatch(value) else None


def _bytes_metadata(value):
    if type(value) is not bytes:
        return None, None
    return len(value), hashlib.sha256(value).hexdigest()


def _write_private(path, payload, *, append=False):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False) + "\n"
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_APPEND if append else os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise OSError("diagnostic_file_unavailable")
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


class RuntimeGuard(BaseRuntimeGuard):
    """Preserve 113 behavior, with one optional sidecar per admitted native request."""

    def __init__(self, *args, preparation_request_seconds=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preparation_request_seconds is not None and (
            type(preparation_request_seconds) not in (int, float)
            or not math.isfinite(preparation_request_seconds) or preparation_request_seconds <= 0
        ):
            raise ValueError("invalid_preparation_request_timeout")
        self.preparation_request_seconds = (
            self._ordinary_request_seconds if preparation_request_seconds is None
            else float(preparation_request_seconds)
        )
        self._observation_local = threading.local()
        self.native_requests = {}
        self._native_requests_lock = threading.Lock()
        self._responses_captured = self._responses_unavailable = 0
        self._transport_captured = self._transport_unavailable = 0
        self._transport_created = False

    @property
    def request_seconds(self):
        # The inherited guard reads its ceiling while admitting each request.
        # Context is thread-local, so a preparation call never raises another
        # thread's ordinary ceiling or requires mutating a shared timeout.
        local = getattr(self, "_observation_local", None)
        context = getattr(local, "request_context", None)
        if context is not None and context["stage"] in {"evaluator_compiler", "evaluator_auditor"}:
            return self.preparation_request_seconds
        return self._ordinary_request_seconds

    @request_seconds.setter
    def request_seconds(self, value):
        self._ordinary_request_seconds = float(value)

    @contextmanager
    def request_context(
        self, stage, *, run_id=None, task_id=None, budget_id=None, max_tool_steps=None,
    ):
        if stage not in _STAGES:
            raise ValueError("invalid_request_stage")
        if stage == "candidate_generation":
            if (any(_safe_token(value) is None for value in (run_id, task_id, budget_id))
                    or type(max_tool_steps) is not int or not 1 <= max_tool_steps <= 200):
                raise ValueError("invalid_candidate_request_context")
        elif any(value is not None for value in (run_id, task_id, budget_id, max_tool_steps)):
            raise ValueError("invalid_preparation_request_context")
        previous = getattr(self._observation_local, "request_context", None)
        if previous is not None:
            raise RuntimeError("nested_request_context")
        context = {
            "stage": stage,
            "run_id": run_id,
            "task_id": task_id,
            "budget_id": budget_id,
            "max_tool_steps": max_tool_steps,
        }
        self._observation_local.request_context = context
        try:
            yield context
        finally:
            self._observation_local.request_context = previous

    def _capture_response(self, index, context, runtime, turn):
        try:
            raw = turn.text.encode("utf-8")
            key = getattr(runtime, "api_key", None)
            text = turn.text.replace(key, "[REDACTED]") if isinstance(key, str) and key else turn.text
            text = _SECRET_RE.sub("[REDACTED]", text)
            redacted = text.encode("utf-8")
            prefix = redacted[:MAX_PREFIX_BYTES].decode("utf-8", errors="ignore")
            prefix_bytes = len(prefix.encode("utf-8"))
            root = self.journal_path.parent / "responses"
            root.mkdir(mode=0o700, exist_ok=True)
            if root.is_symlink() or not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700:
                raise OSError("response_directory_unavailable")
            _write_private(root / f"response-{index:03d}.json", {
                "schema_version": "1", "request_index": index,
                "capture_scope": "parsed_assistant_text_only",
                "stage": context["stage"] if context is not None else "unbound",
                "tool_call_count": len(turn.tool_calls),
                "text_utf8_bytes": len(raw), "text_sha256": hashlib.sha256(raw).hexdigest(),
                "redaction_applied": text != turn.text,
                "redacted_prefix": prefix, "redacted_prefix_utf8_bytes": prefix_bytes,
                "truncated": prefix_bytes < len(redacted),
            })
        except Exception:  # noqa: BLE001 - optional diagnostics cannot alter native outcomes
            self._responses_unavailable += 1
        else:
            self._responses_captured += 1

    def _capture_transport(self, record):
        try:
            messages, tools = record["messages"], record["tools"]
            roles = [item.get("role") if type(item) is dict else None for item in messages]
            roles = [role if type(role) is str and role in _ROLES else "other" for role in roles]
            row = {
                "schema_version": "1", "request_index": record["index"],
                "stage": (record["context"]["stage"]
                          if record["context"] is not None else "unbound"),
                "context_bound": record["context"] is not None,
                "run_id": None, "task_id": None, "budget_id": None,
                "max_tool_steps": None, "message_count": len(messages),
                "message_roles": roles, "tool_count": len(tools),
                "exchange_count": len(record["exchanges"]), "outcome": "unavailable",
                "request_body_bytes": None, "request_sha256": None,
                "status": None, "elapsed_ms": None, "transport_observation": None,
                "response_body_bytes": None, "response_body_sha256": None,
                "failure_reason": None, "failure_phase": None,
            }
            if record["context"] is not None:
                for key in ("run_id", "task_id", "budget_id", "max_tool_steps"):
                    row[key] = record["context"][key]
            if len(record["exchanges"]) == 1:
                request, result, outcome, started, ended = record["exchanges"][0]
                row["request_body_bytes"], row["request_sha256"] = _bytes_metadata(request.data)
                row["outcome"], row["elapsed_ms"] = outcome, _elapsed(started, ended)
                if result is not None:
                    status = result.status
                    row["status"] = status if type(status) is int and 100 <= status <= 599 else None
                    row["response_body_bytes"], row["response_body_sha256"] = _bytes_metadata(
                        result.body,
                    )
                    detail = result.observation
                    if type(detail) is TransportObservation:
                        try:
                            row["transport_observation"] = normalize_transport_observation({
                                "last_milestone": detail.last_milestone,
                                "http_exchange_index": detail.http_exchange_index,
                                "elapsed_ms": detail.elapsed_ms,
                            })
                        except (ValueError, TypeError):
                            pass
                    if outcome == "failure":
                        row["failure_reason"] = result.reason if result.reason in _REASONS else None
                        row["failure_phase"] = result.phase if result.phase in _PHASES else None
            path = self.journal_path.parent / "transport.jsonl"
            _write_private(path, row, append=self._transport_created)
            self._transport_created = True
        except Exception:  # noqa: BLE001 - missing metadata cannot change native accounting
            self._transport_unavailable += 1
        else:
            self._transport_captured += 1

    def complete(self, native, runtime, messages, tools=(), timeout=None):
        record = None
        observed = None
        native_failure = None

        def observed_native(model, request_messages, request_tools=(), request_timeout=None):
            nonlocal record, observed, native_failure
            context = getattr(self._observation_local, "request_context", None)
            record = {"index": self.requests, "messages": request_messages,
                      "tools": request_tools, "exchanges": [],
                      "context": dict(context) if context is not None else None}
            previous = getattr(self._observation_local, "record", None)
            self._observation_local.record = record
            try:
                turn = native(model, request_messages, request_tools, request_timeout)
                if isinstance(turn, ModelTurn):
                    observed = model, turn
                return turn
            except ModelRequestFailure as exc:
                if type(exc) is ModelRequestFailure:
                    native_failure = exc
                raise
            finally:
                self._observation_local.record = previous

        try:
            return super().complete(observed_native, runtime, messages, tools, timeout)
        except MeasurementRuntimeError as exc:
            # The base emits provider_error only after the finish row has been fsynced.
            # Journal/admission failures retain their own outcome, and a later stopped
            # call has no native_failure/record to restore from a prior request.
            if (type(exc) is MeasurementRuntimeError and exc.args == ("provider_error",)
                    and native_failure is not None and record is not None
                    and self.stopped_reason == "provider_error"
                    and self.finished_requests == self.requests == record["index"]):
                raise native_failure from None
            raise
        finally:
            # All serialization, hashing and persistence occur after the frozen ledger accepts
            # or rejects the response. They cannot create a late-response rejection in this call.
            if record is not None:
                self._capture_transport(record)
                if observed is not None:
                    self._capture_response(record["index"], record["context"], *observed)

    def snapshot(self):
        result = super().snapshot()
        result["response_diagnostics"] = {
            "captured": self._responses_captured, "unavailable": self._responses_unavailable,
        }
        result["transport_diagnostics"] = {
            "captured": self._transport_captured, "unavailable": self._transport_unavailable,
        }
        result["native_trace"] = getattr(self, "native_trace", None)
        return result


@contextmanager
def observed_guard(guard):
    """Install request accounting and high-level native ownership wrappers."""
    native_exchange = runtime_module.exchange
    native_contract_compile = RuntimeContractCompiler.compile
    native_evaluator_run = evaluator_bundle_module._run_isolated
    native_agent_run = RuntimeAgentAdapter.run

    def exchange(request, timeout):
        result, outcome, started = None, "unavailable", _clock()
        try:
            result = native_exchange(request, timeout)
            outcome = "response"
            return result
        except TransportFailure as failure:
            result, outcome = failure, "failure"
            raise
        finally:
            ended = _clock()
            try:
                record = getattr(guard._observation_local, "record", None)
                if record is not None:
                    record["exchanges"].append((request, result, outcome, started, ended))
            except Exception:  # noqa: BLE001, S110 - preserve the original transport outcome
                pass

    def contract_compile(compiler, *args, **kwargs):
        with guard.request_context("contract_compiler"):
            return native_contract_compile(compiler, *args, **kwargs)

    def evaluator_run(runtime, prompt, workspace, timeout):
        name = Path(workspace).name
        stage = {
            ".evaluator-compiler": "evaluator_compiler",
            ".evaluator-auditor": "evaluator_auditor",
        }.get(name)
        if stage is None:
            return native_evaluator_run(runtime, prompt, workspace, timeout)
        with guard.request_context(stage):
            return native_evaluator_run(runtime, prompt, workspace, timeout)

    def agent_run(adapter, request):
        if not isinstance(request, AgentRequest) or request.candidate_budget is None:
            return native_agent_run(adapter, request)
        budget = request.candidate_budget
        with guard.request_context(
            "candidate_generation",
            run_id=request.run_id,
            task_id=request.task_id,
            budget_id=budget.budget_id,
            max_tool_steps=budget.max_tool_steps,
        ) as context:
            with guard._native_requests_lock:
                if budget.budget_id in guard.native_requests:
                    raise RuntimeError("duplicate_native_candidate_budget")
                guard.native_requests[budget.budget_id] = {
                    **context, "started_at": guard.clock() - guard.started, "finished_at": None,
                }
            try:
                return native_agent_run(adapter, request)
            finally:
                with guard._native_requests_lock:
                    guard.native_requests[budget.budget_id]["finished_at"] = guard.clock() - guard.started

    with _shared.installed_guard(guard):
        runtime_module.exchange = exchange
        RuntimeContractCompiler.compile = contract_compile
        evaluator_bundle_module._run_isolated = evaluator_run
        RuntimeAgentAdapter.run = agent_run
        try:
            yield guard
        finally:
            RuntimeAgentAdapter.run = native_agent_run
            evaluator_bundle_module._run_isolated = native_evaluator_run
            RuntimeContractCompiler.compile = native_contract_compile
            runtime_module.exchange = native_exchange
