"""Campaign-local request accounting; never changes the native request or retries it.

The observed-token threshold can stop subsequent spending and reject its triggering response;
it cannot bound unreported provider consumption or the size of a response already requested.
An outer process supervisor must enforce the whole attempt's wall-clock deadline, including
local candidate/evaluator work. The guard caps each native HTTP call by the remaining deadline.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from famou.runtime import (
    MODEL_FAILURE_REASONS,
    ModelRequestFailure,
    ModelTurn,
    OpenAICompatibleRuntime,
)


class MeasurementRuntimeError(RuntimeError):
    """Only fixed campaign diagnostics cross the worker boundary."""


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _model(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > 128 or any(ord(char) < 33 for char in value)):
        raise MeasurementRuntimeError("provider_model_invalid")
    return value


@dataclass(frozen=True)
class ProviderConfiguration:
    endpoint: str
    api_key: str = field(repr=False)
    configured_model: str
    configured_wire_api: str | None = None
    configured_reasoning_effort: str | None = None

    def safe_metadata(self, requested_model: str) -> dict[str, object]:
        """Explicit requested model is independent of the CC Switch application's model."""
        return {
            "source": "cc_switch_selected_codex_provider",
            "endpoint_sha256": _sha(self.endpoint),
            "chat_endpoint_sha256": _sha(OpenAICompatibleRuntime._chat_endpoint(self.endpoint)),
            "configured_model": self.configured_model,
            "configured_wire_api": self.configured_wire_api,
            "configured_reasoning_effort": self.configured_reasoning_effort,
            "requested_model": _model(requested_model),
            "native_wire_api": "chat_completions",
            "native_reasoning_parameter": None,
            "credential_present": bool(self.api_key),
        }


def load_provider(
    root: Path | None = None, *, requested_model: str,
    expected: dict[str, object] | None = None,
) -> ProviderConfiguration:
    """Read only the currently selected Codex provider; never load Claude or print secrets."""
    try:
        root = Path.home() / ".cc-switch" if root is None else Path(root)
        settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        database = (root / "cc-switch.db").resolve(strict=True)
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT settings_config FROM providers WHERE app_type=? AND id=?",
                ("codex", settings["currentProviderCodex"]),
            ).fetchone()
        configured = json.loads(row[0])
        config = tomllib.loads(configured["config"])
        provider = config["model_providers"][config["model_provider"]]
        endpoint = provider["base_url"].rstrip("/")
        url = urlsplit(endpoint)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise ValueError("invalid endpoint")
        key = configured["auth"]["OPENAI_API_KEY"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("missing credential")
        wire_api, effort = provider.get("wire_api"), config.get("model_reasoning_effort")
        for value in (wire_api, effort):
            if value is not None and (not isinstance(value, str) or len(value) > 128):
                raise ValueError("invalid metadata")
        result = ProviderConfiguration(endpoint, key, _model(config["model"]), wire_api, effort)
        metadata = result.safe_metadata(requested_model)
        if expected is not None and metadata != expected:
            raise MeasurementRuntimeError("provider_registration_mismatch")
        return result
    except MeasurementRuntimeError:
        raise
    except Exception:  # noqa: BLE001 - configuration errors must never print credentials
        raise MeasurementRuntimeError("provider_configuration_unavailable") from None


class RuntimeGuard:
    """One shared ledger for all runtimes and roles within one registered attempt."""

    def __init__(
        self, provider: ProviderConfiguration, requested_model: str, journal_path: Path, *,
        max_requests: int = 16, token_stop_threshold: int = 160_000,
        wall_seconds: float = 1200.0, request_seconds: float = 180.0,
        clock=time.monotonic,
    ) -> None:
        for value in (max_requests, token_stop_threshold):
            if type(value) is not int or value <= 0:
                raise MeasurementRuntimeError("guard_settings_invalid")
        for value in (wall_seconds, request_seconds):
            if type(value) not in {float, int} or not math.isfinite(value) or value <= 0:
                raise MeasurementRuntimeError("guard_settings_invalid")
        self.provider, self.requested_model = provider, _model(requested_model)
        self.journal_path = Path(journal_path)
        self.max_requests, self.token_stop_threshold = max_requests, token_stop_threshold
        self.wall_seconds, self.request_seconds = float(wall_seconds), float(request_seconds)
        self.clock, self.started = clock, clock()
        self.requests = self.finished_requests = 0
        self.known_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.usage_complete = True
        self.stopped_reason: str | None = None
        self._lock = threading.Lock()
        self._installed = False
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        # A previously started attempt can never acquire a fresh ledger or replacement slots.
        with self.journal_path.open("x", encoding="utf-8"):
            pass

    def _append(self, row: dict[str, object]) -> None:
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:  # noqa: BLE001 - preserve a fixed failure if journal persistence fails
            self.stopped_reason = "request_journal_unavailable"
            raise MeasurementRuntimeError(self.stopped_reason) from None

    def snapshot(self) -> dict[str, object]:
        return {
            "provider_requests": self.requests,
            "finished_requests": self.finished_requests,
            "known_usage": dict(self.known_usage),
            "usage_complete": self.usage_complete and self.requests == self.finished_requests,
            "stopped_reason": self.stopped_reason,
            "elapsed_seconds": max(0.0, self.clock() - self.started),
        }

    def _stop(self, reason: str) -> None:
        self.stopped_reason = reason
        raise MeasurementRuntimeError(reason)

    def _check_identity(self, runtime: OpenAICompatibleRuntime) -> None:
        if (runtime.endpoint != OpenAICompatibleRuntime._chat_endpoint(self.provider.endpoint)
                or runtime.model != self.requested_model
                or runtime.api_key != self.provider.api_key):
            self._stop("runtime_registration_mismatch")

    def complete(self, native, runtime, messages, tools=(), timeout=None) -> ModelTurn:
        # Serialize admission and accounting even if an accidental extra runtime/thread appears.
        with self._lock:
            if self.stopped_reason is not None:
                raise MeasurementRuntimeError(self.stopped_reason)
            self._check_identity(runtime)
            if self.requests >= self.max_requests:
                self._stop("request_limit_reached")
            if self.known_usage["total_tokens"] >= self.token_stop_threshold:
                self._stop("observed_token_threshold_reached")
            remaining = self.wall_seconds - (self.clock() - self.started)
            if remaining <= 0:
                self._stop("attempt_deadline_reached")
            if timeout is not None and (
                type(timeout) not in {float, int} or not math.isfinite(timeout) or timeout <= 0
            ):
                self._stop("request_timeout_invalid")
            effective = min(remaining, self.request_seconds,
                            self.request_seconds if timeout is None else timeout)
            body = {"model": self.requested_model, "messages": messages, "stream": False,
                    **({"tools": list(tools)} if tools else {})}
            request_hash = _sha(json.dumps(body, ensure_ascii=False))
            index, started = self.requests + 1, self.clock()
            self._append({
                "kind": "request_started", "index": index,
                "requested_model": self.requested_model, "request_sha256": request_hash,
                "request_timeout_seconds": effective,
                "elapsed_seconds": max(0.0, started - self.started),
            })
            self.requests = index
            outcome, usage, response_model, model_hash = "provider_error", None, None, None
            failure_reason, response_status = None, None
            observation = None
            turn = None
            try:
                turn = native(runtime, messages, tools, effective)
                if not isinstance(turn, ModelTurn):
                    outcome = "invalid_turn"
                else:
                    raw_model = turn.response_model
                    if isinstance(raw_model, str):
                        model_hash = _sha(raw_model)
                    # Unknown provider prose never enters public model-name fields.
                    response_model = raw_model if raw_model == self.requested_model else None
                    raw_usage = turn.usage
                    if (isinstance(raw_usage, dict)
                            and set(raw_usage) == set(self.known_usage)
                            and all(type(value) is int and value >= 0 for value in raw_usage.values())
                            and raw_usage["input_tokens"] + raw_usage["output_tokens"]
                            == raw_usage["total_tokens"]):
                        usage = dict(raw_usage)
                        for key, value in usage.items():
                            self.known_usage[key] += value
                    if response_model is None:
                        outcome = "response_model_mismatch"
                    elif usage is None:
                        outcome = "usage_unavailable"
                    elif self.clock() - self.started >= self.wall_seconds:
                        outcome = "attempt_deadline_reached"
                    elif self.known_usage["total_tokens"] >= self.token_stop_threshold:
                        outcome = "observed_token_threshold_reached"
                    else:
                        outcome = "succeeded"
            except ModelRequestFailure as exc:
                reason, status = exc.evidence.reason, exc.evidence.response_status
                failure_reason = reason if isinstance(reason, str) and reason in MODEL_FAILURE_REASONS else None
                response_status = status if type(status) is int and 100 <= status <= 599 else None
                observed = exc.observation
                if observed is not None and isinstance(observed.phase, str) and observed.phase in {
                    "open_response", "read_response_body", "read_http_error_body", "validate_response",
                } and type(observed.elapsed_ms) is int and 0 <= observed.elapsed_ms <= 10**12 and (
                    observed.request_timeout_ms is None or type(observed.request_timeout_ms) is int
                    and 0 <= observed.request_timeout_ms <= 10**12
                ):
                    observation = {
                        "phase": observed.phase, "elapsed_ms": observed.elapsed_ms,
                        "request_timeout_ms": observed.request_timeout_ms,
                    }
            except BaseException:  # noqa: BLE001 - failed/interrupted requests have unknown usage
                # Account interrupted/failed provider consumption as unknown, including Ctrl-C.
                # Only a fixed exception is raised after durable accounting; never provider prose.
                outcome = "provider_error"
            finally:
                if usage is None:
                    self.usage_complete = False
                if outcome != "succeeded":
                    self.stopped_reason = outcome
                self.finished_requests += 1
                self._append({
                    "kind": "request_finished", "index": index, "outcome": outcome,
                    "elapsed_seconds": max(0.0, self.clock() - started),
                    "response_model": response_model, "response_model_sha256": model_hash,
                    "usage": usage, "known_usage": dict(self.known_usage),
                    "usage_complete": self.usage_complete,
                    "failure_reason": failure_reason, "response_status": response_status,
                    "observation": observation,
                })
            if outcome != "succeeded":
                raise MeasurementRuntimeError(outcome) from None
            return turn


@contextmanager
def installed_guard(guard: RuntimeGuard):
    """Patch only this worker; native runtime behavior and payload construction stay intact."""
    if guard._installed:
        raise MeasurementRuntimeError("guard_already_installed")
    guard._installed = True
    native_init, native_complete = OpenAICompatibleRuntime.__init__, OpenAICompatibleRuntime.complete
    private_environment = {
        key: value for key, value in os.environ.items()
        if key.startswith(("FAMOU_MODEL", "FAMOU_API", "OPENAI_", "ANTHROPIC_"))
    }
    for key in private_environment:
        os.environ.pop(key, None)

    def initialize(runtime, endpoint=None, model=None, api_key=None):
        if (endpoint is not None and endpoint != guard.provider.endpoint
                or model is not None and model != guard.requested_model
                or api_key is not None and api_key != guard.provider.api_key):
            guard._stop("runtime_registration_mismatch")
        native_init(runtime, guard.provider.endpoint, guard.requested_model, guard.provider.api_key)

    def complete(runtime, messages, tools=(), timeout=None):
        return guard.complete(native_complete, runtime, messages, tools, timeout)

    OpenAICompatibleRuntime.__init__, OpenAICompatibleRuntime.complete = initialize, complete
    try:
        yield guard
    finally:
        OpenAICompatibleRuntime.__init__, OpenAICompatibleRuntime.complete = native_init, native_complete
        os.environ.update(private_environment)
        guard._installed = False
