"""Optional private diagnostics around the frozen 113 request ledger.

The ledger retains its original admission, accounting and failure rules. Observation extracts
safe metadata only after that accounting; exchange returns/rethrows the original native object.
Local transport milestones do not establish provider receipt, execution or billable consumption.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import famou.runtime as runtime_module
from famou.http_transport import (
    TransportFailure,
    TransportObservation,
    normalize_transport_observation,
)
from famou.runtime import _SECRET_RE, ModelTurn


def _load_shared_runtime():
    path = (Path(__file__).resolve().parents[3]
            / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py")
    name = "_lunar_measurement131_frozen113_runtime_guard"
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


def _stage(index):
    return {1: "contract_compiler", 2: "evaluator_compiler", 3: "evaluator_auditor"}.get(index, "candidate")


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observation_local = threading.local()
        self._responses_captured = self._responses_unavailable = 0
        self._transport_captured = self._transport_unavailable = 0
        self._transport_created = False

    def _capture_response(self, index, runtime, turn):
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
                "capture_scope": "parsed_assistant_text_only", "stage_hint": _stage(index),
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
                "stage": _stage(record["index"]), "message_count": len(messages),
                "message_roles": roles, "tool_count": len(tools),
                "exchange_count": len(record["exchanges"]), "outcome": "unavailable",
                "request_body_bytes": None, "request_sha256": None,
                "status": None, "elapsed_ms": None, "transport_observation": None,
                "response_body_bytes": None, "response_body_sha256": None,
                "failure_reason": None, "failure_phase": None,
            }
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

        def observed_native(model, request_messages, request_tools=(), request_timeout=None):
            nonlocal record, observed
            record = {"index": self.requests, "messages": request_messages,
                      "tools": request_tools, "exchanges": []}
            previous = getattr(self._observation_local, "record", None)
            self._observation_local.record = record
            try:
                turn = native(model, request_messages, request_tools, request_timeout)
                if isinstance(turn, ModelTurn):
                    observed = model, turn
                return turn
            finally:
                self._observation_local.record = previous

        try:
            return super().complete(observed_native, runtime, messages, tools, timeout)
        finally:
            # All serialization, hashing and persistence occur after the frozen ledger accepts
            # or rejects the response. They cannot create a late-response rejection in this call.
            if record is not None:
                self._capture_transport(record)
                if observed is not None:
                    self._capture_response(record["index"], *observed)

    def snapshot(self):
        result = super().snapshot()
        result["response_diagnostics"] = {
            "captured": self._responses_captured, "unavailable": self._responses_unavailable,
        }
        result["transport_diagnostics"] = {
            "captured": self._transport_captured, "unavailable": self._transport_unavailable,
        }
        return result


@contextmanager
def observed_guard(guard):
    """Install the base guard plus one passive local exchange observer, then restore both."""
    native_exchange = runtime_module.exchange

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

    with _shared.installed_guard(guard):
        runtime_module.exchange = exchange
        try:
            yield guard
        finally:
            runtime_module.exchange = native_exchange
