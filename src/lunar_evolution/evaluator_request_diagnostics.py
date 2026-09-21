"""Bounded model-request observations for evaluator preparation failures.

These observations explain an existing failure. They grant no recovery authority and say
nothing about remote completion, provider activity, token usage, or evaluator quality.
"""

from __future__ import annotations

from .http_transport import TransportObservation, normalize_transport_observation
from .runtime import (
    MAX_REQUEST_OBSERVATION_MS,
    MODEL_FAILURE_REASONS,
    ModelFailureEvidence,
    ModelRequestFailure,
    ModelRequestObservation,
)

_FIELDS = {
    "schema_version", "reason", "response_status", "request_observation", "transport_observation",
}


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _request_observation(value: object, reason: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != {"phase", "elapsed_ms", "request_timeout_ms"}:
        raise ValueError("invalid evaluator request observation fields")
    if reason in {"transport_timeout", "transport_error"}:
        phases = {"open_response", "read_response_body"}
    elif reason == "http_error":
        phases = {"read_http_error_body", "validate_response"}
    else:
        phases = {"validate_response"}
    if type(value["phase"]) is not str or value["phase"] not in phases:
        raise ValueError("inconsistent evaluator request phase")
    if not _integer(value["elapsed_ms"], 0, MAX_REQUEST_OBSERVATION_MS):
        raise ValueError("invalid evaluator request elapsed time")
    timeout = value["request_timeout_ms"]
    if timeout is not None and not _integer(timeout, 0, MAX_REQUEST_OBSERVATION_MS):
        raise ValueError("invalid evaluator request timeout")
    return dict(value)


def normalize_evaluator_request_failure(value: object) -> dict[str, object]:
    """Validate and copy the fixed protocol, rejecting arbitrary text and extra fields."""
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("invalid evaluator request failure fields")
    if type(value["schema_version"]) is not str or value["schema_version"] != "1":
        raise ValueError("invalid evaluator request failure version")
    reason, status = value["reason"], value["response_status"]
    if type(reason) is not str or reason not in MODEL_FAILURE_REASONS:
        raise ValueError("invalid evaluator request failure reason")
    if status is not None and not _integer(status, 100, 599):
        raise ValueError("invalid evaluator response status")
    if status is not None:
        if reason == "http_error" and 200 <= status <= 299:
            raise ValueError("inconsistent evaluator HTTP failure status")
        if (reason not in {"http_error", "transport_timeout", "transport_error"}
                and not 200 <= status <= 299):
            raise ValueError("inconsistent evaluator response validation status")
    request = value["request_observation"]
    if request is not None:
        request = _request_observation(request, reason)
    transport = value["transport_observation"]
    if transport is not None:
        if request is None:
            raise ValueError("transport observation requires evaluator request observation")
        transport = normalize_transport_observation(transport)
    return {**value, "request_observation": request, "transport_observation": transport}


def project_evaluator_request_failure(error: object) -> dict[str, object] | None:
    """Project only the direct owned failure; malformed optional detail degrades safely."""
    if type(error) is not ModelRequestFailure:
        return None
    try:
        evidence = error.evidence
        if type(evidence) is not ModelFailureEvidence:
            return None
        result = normalize_evaluator_request_failure({
            "schema_version": "1", "reason": evidence.reason,
            "response_status": evidence.response_status,
            "request_observation": None, "transport_observation": None,
        })
    except Exception:  # noqa: BLE001 - diagnostics must never mask the runtime failure
        return None
    try:
        observation = error.observation
        if type(observation) is not ModelRequestObservation:
            return result
        result["request_observation"] = _request_observation({
            "phase": observation.phase, "elapsed_ms": observation.elapsed_ms,
            "request_timeout_ms": observation.request_timeout_ms,
        }, result["reason"])
    except Exception:  # noqa: BLE001 - retain the valid base if optional timing is malformed
        return result
    try:
        transport = error.transport_observation
        if type(transport) is TransportObservation:
            result["transport_observation"] = normalize_transport_observation({
                "last_milestone": transport.last_milestone,
                "http_exchange_index": transport.http_exchange_index,
                "elapsed_ms": transport.elapsed_ms,
            })
    except Exception:  # noqa: BLE001 - retain valid base/timing if transport detail is malformed
        return result
    return result
