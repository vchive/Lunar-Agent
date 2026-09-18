"""Evaluator request failures retain bounded facts, never provider text or recovery authority."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_frozen_evaluator_bundle import BundleRuntime, _compile_bundle, _contract, _envelope
from test_http_transport_deadline import assert_closed, local_http, spy_processes
from test_model_failure_evidence import chat, local_model

from famou.evaluator_bundle import EvaluatorBundleRuntimeError, compile_evaluator_bundle
from famou.evaluator_request_diagnostics import (
    normalize_evaluator_request_failure,
    project_evaluator_request_failure,
)
from famou.evolution import CandidateInputArtifact
from famou.http_transport import TransportObservation
from famou.runtime import (
    MAX_REQUEST_OBSERVATION_MS,
    MODEL_FAILURE_REASONS,
    ModelFailureEvidence,
    ModelRequestFailure,
    ModelRequestObservation,
    OpenAICompatibleRuntime,
)

PRIVATE = "PRIVATE-FAILURE-TEXT-SENTINEL"


def _failure(reason="transport_timeout", status=None, phase="open_response"):
    error = ModelRequestFailure(PRIVATE, reason, status)
    error.observation = ModelRequestObservation(phase, 1234, 1000)
    error.transport_observation = TransportObservation("wait_response_headers", 1, 1230)
    return error


def _payload():
    return {
        "schema_version": "1", "reason": "transport_timeout", "response_status": None,
        "request_observation": {
            "phase": "open_response", "elapsed_ms": 1234, "request_timeout_ms": 1000,
        },
        "transport_observation": {
            "last_milestone": "wait_response_headers", "http_exchange_index": 1, "elapsed_ms": 1230,
        },
    }


@pytest.mark.parametrize("reason", sorted(MODEL_FAILURE_REASONS))
@pytest.mark.parametrize("status_present", [False, True])
def test_runtime_reason_status_and_phase_vocabulary(reason, status_present):
    status = (429 if reason == "http_error" else 200) if status_present else None
    phase = ("open_response" if reason.startswith("transport_") else
             "read_http_error_body" if reason == "http_error" else "validate_response")
    error = _failure(reason, status, phase)
    payload = project_evaluator_request_failure(error)
    assert payload["reason"] == reason and payload["response_status"] == status
    assert payload["request_observation"]["phase"] == phase
    assert normalize_evaluator_request_failure(payload) == payload
    assert PRIVATE not in json.dumps(payload)
    assert set(payload) == set(_payload())


@pytest.mark.parametrize("changes", [
    {"schema_version": 1}, {"schema_version": "2"}, {"reason": []}, {"reason": "unknown"},
    {"response_status": True}, {"response_status": 99}, {"response_status": 600},
    {"response_status": "429"}, {"reason": "http_error", "response_status": 200},
    {"reason": "invalid_usage", "response_status": 429},
    {"reason": "invalid_json"}, {"private_response": PRIVATE},
    {"request_observation": None}, {"request_observation": []},
    {"transport_observation": []},
])
def test_persisted_inconsistent_or_extra_fields_are_rejected(changes):
    value = {**_payload(), **changes}
    with pytest.raises(ValueError):
        normalize_evaluator_request_failure(value)


@pytest.mark.parametrize("field", list(_payload()))
def test_every_projection_field_is_required(field):
    value = _payload()
    del value[field]
    with pytest.raises(ValueError):
        normalize_evaluator_request_failure(value)


@pytest.mark.parametrize("section,changes", [
    ("request_observation", {"phase": []}),
    ("request_observation", {"phase": "validate_response"}),
    ("request_observation", {"elapsed_ms": True}),
    ("request_observation", {"elapsed_ms": -1}),
    ("request_observation", {"elapsed_ms": MAX_REQUEST_OBSERVATION_MS + 1}),
    ("request_observation", {"request_timeout_ms": True}),
    ("request_observation", {"request_timeout_ms": -1}),
    ("request_observation", {"request_timeout_ms": MAX_REQUEST_OBSERVATION_MS + 1}),
    ("request_observation", {"request_body": PRIVATE}),
    ("transport_observation", {"last_milestone": "provider_generating"}),
    ("transport_observation", {"http_exchange_index": True}),
    ("transport_observation", {"http_exchange_index": 0}),
    ("transport_observation", {"elapsed_ms": -1}),
    ("transport_observation", {"response_body": PRIVATE}),
])
def test_persisted_nested_corruption_is_rejected(section, changes):
    value = _payload()
    value[section].update(changes)
    with pytest.raises(ValueError):
        normalize_evaluator_request_failure(value)


def test_nullable_observations_and_timeout_are_not_inferred():
    bare = ModelRequestFailure(PRIVATE, "transport_timeout")
    payload = project_evaluator_request_failure(bare)
    assert payload == {**_payload(), "request_observation": None, "transport_observation": None}
    bare.observation = ModelRequestObservation("open_response", 0, None)
    payload = project_evaluator_request_failure(bare)
    assert payload["request_observation"] == {
        "phase": "open_response", "elapsed_ms": 0, "request_timeout_ms": None,
    }
    assert payload["response_status"] is None and payload["transport_observation"] is None
    bare.observation = ModelRequestObservation("open_response", MAX_REQUEST_OBSERVATION_MS, 0)
    assert project_evaluator_request_failure(bare)["request_observation"]["request_timeout_ms"] == 0


def test_projection_and_runtime_exception_copy_nested_observations():
    payload = _payload()
    normalized = normalize_evaluator_request_failure(payload)
    error = EvaluatorBundleRuntimeError("evaluator_compile", request_failure=payload)
    payload["request_observation"]["elapsed_ms"] = 1
    payload["transport_observation"]["elapsed_ms"] = 1
    assert normalized == error.request_failure == _payload()
    normalized["request_observation"]["elapsed_ms"] = 2
    assert error.request_failure == _payload()
    assert str(error) == "evaluator compiler failed: runtime_error"
    with pytest.raises(ValueError):
        EvaluatorBundleRuntimeError("evaluator_audit", request_failure={"body": PRIVATE})


@pytest.mark.parametrize("kind", ["foreign", "subclass", "missing", "unknown", "bool", "status"])
def test_malformed_base_evidence_never_replaces_original_failure(kind):
    error = _failure()
    if kind == "foreign":
        error.evidence = {"reason": "transport_timeout", "response_status": None}
    elif kind == "subclass":
        class Foreign(ModelFailureEvidence):
            pass
        error.evidence = Foreign("transport_timeout", None)
    elif kind == "missing":
        del error.evidence
    else:
        changes = {"unknown": {"reason": PRIVATE}, "bool": {"response_status": True},
                   "status": {"reason": "invalid_json", "response_status": 500}}
        error.evidence = replace(error.evidence, **changes[kind])
    assert project_evaluator_request_failure(error) is None
    assert str(error) == PRIVATE


@pytest.mark.parametrize("kind", ["foreign", "subclass", "missing", "phase", "bool", "deleted"])
def test_malformed_request_observation_drops_both_observations(kind):
    error = _failure()
    if kind == "foreign":
        error.observation = _payload()["request_observation"]
    elif kind == "subclass":
        class Foreign(ModelRequestObservation):
            pass
        error.observation = Foreign("open_response", 1, 1000)
    elif kind == "missing":
        del error.observation
    elif kind == "deleted":
        object.__delattr__(error.observation, "elapsed_ms")
    else:
        error.observation = replace(error.observation, **(
            {"phase": "validate_response"} if kind == "phase" else {"elapsed_ms": True}
        ))
    assert project_evaluator_request_failure(error) == {
        **_payload(), "request_observation": None, "transport_observation": None,
    }


@pytest.mark.parametrize("kind", ["foreign", "subclass", "missing", "milestone", "bool", "deleted"])
def test_malformed_transport_observation_drops_only_transport(kind):
    error = _failure()
    if kind == "foreign":
        error.transport_observation = _payload()["transport_observation"]
    elif kind == "subclass":
        class Foreign(TransportObservation):
            pass
        error.transport_observation = Foreign("wait_response_headers", 1, 1000)
    elif kind == "missing":
        del error.transport_observation
    elif kind == "deleted":
        object.__delattr__(error.transport_observation, "elapsed_ms")
    else:
        error.transport_observation = replace(error.transport_observation, **(
            {"last_milestone": PRIVATE} if kind == "milestone" else {"http_exchange_index": True}
        ))
    assert project_evaluator_request_failure(error) == {**_payload(), "transport_observation": None}


def test_only_direct_concrete_error_is_accepted_and_no_cause_details_are_borrowed():
    inner = _failure()
    wrapper = RuntimeError(PRIVATE)
    wrapper.__cause__ = inner
    assert project_evaluator_request_failure(wrapper) is None

    class Foreign(ModelRequestFailure):
        def __getattribute__(self, name):
            raise AssertionError("foreign exception must not be inspected")

    assert project_evaluator_request_failure(Foreign(PRIVATE, "transport_timeout")) is None
    outer = ModelRequestFailure(PRIVATE, "invalid_usage", 200)
    outer.__cause__ = inner
    assert project_evaluator_request_failure(outer) == {
        **_payload(), "reason": "invalid_usage", "response_status": 200,
        "request_observation": None, "transport_observation": None,
    }


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("typed", [False, True])
def test_compiler_and_auditor_preserve_direct_cause_and_safe_projection(
    tmp_path, stage, isolated, typed,
):
    original = _failure() if typed else RuntimeError(PRIVATE)
    if not typed:
        original.__cause__ = _failure()
    calls = []

    class FailingRuntime(BundleRuntime):
        def invoke(self, prompt, workspace, timeout):
            actual = ("evaluator_audit" if "adversarial evaluator auditor" in prompt
                      else "evaluator_compile")
            calls.append((actual, timeout))
            if actual == stage:
                raise original
            return super().run(prompt, workspace, timeout)

        def run(self, prompt, workspace, timeout):
            assert not isolated
            return self.invoke(prompt, workspace, timeout)

    runtime = FailingRuntime()
    if isolated:
        runtime.run_isolated = runtime.invoke
    with pytest.raises(EvaluatorBundleRuntimeError) as caught:
        _compile_bundle(runtime, tmp_path)
    error = caught.value
    assert error.__cause__ is original and error.stage == stage
    assert error.request_failure == (_payload() if typed else None)
    assert calls == ([("evaluator_compile", 2)] if stage == "evaluator_compile" else
                     [("evaluator_compile", 2), ("evaluator_audit", 2)])
    assert PRIVATE not in str(error)
    assert not (tmp_path / "evaluator-bundle").exists()
    assert not list(tmp_path.glob(".evaluator-bundle-*"))
    if typed:
        before = deepcopy(error.request_failure)
        original.observation = None
        assert error.request_failure == before


def test_loopback_headers_timeout_reaches_compiler_and_worker_is_reaped(tmp_path, monkeypatch):
    processes, _ = spy_processes(monkeypatch)
    raw = tmp_path / "data/raw/orders.csv"
    raw.parent.mkdir(parents=True)
    content = b"id\nfixture-order\n"
    raw.write_bytes(content)
    artifact = CandidateInputArtifact(
        "data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest(),
    )
    with local_http("headers") as (endpoint, calls):
        runtime = OpenAICompatibleRuntime(endpoint, "fixture", PRIVATE)
        with pytest.raises(EvaluatorBundleRuntimeError) as caught:
            compile_evaluator_bundle(runtime, _contract(), tmp_path, inputs=(artifact,), timeout=0.5)
    payload = caught.value.request_failure
    assert type(caught.value.__cause__) is ModelRequestFailure
    assert caught.value.stage == "evaluator_compile"
    assert payload["reason"] == "transport_timeout" and payload["response_status"] is None
    assert payload["request_observation"]["phase"] == "open_response"
    assert payload["request_observation"]["request_timeout_ms"] == 500
    assert payload["transport_observation"]["last_milestone"] == "wait_response_headers"
    assert len(calls) == 1 and len(processes) == 1
    assert_closed(processes)
    assert PRIVATE not in json.dumps(payload) and endpoint not in json.dumps(payload)
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
def test_loopback_http_status_survives_compiler_and_auditor_boundaries(tmp_path, stage):
    responses = [(429, {"error": PRIVATE})]
    if stage == "evaluator_audit":
        responses.insert(0, (200, chat(json.dumps(_envelope()))))
    with local_model(*responses) as (endpoint, calls):
        runtime = OpenAICompatibleRuntime(endpoint, "fixture", PRIVATE)
        with pytest.raises(EvaluatorBundleRuntimeError) as caught:
            _compile_bundle(runtime, tmp_path)
    payload = caught.value.request_failure
    assert caught.value.stage == stage and len(calls) == len(responses)
    assert payload["reason"] == "http_error" and payload["response_status"] == 429
    assert payload["request_observation"]["phase"] == "read_http_error_body"
    assert payload["transport_observation"]["last_milestone"] == "response_headers_received"
    assert PRIVATE not in json.dumps(payload) and endpoint not in json.dumps(payload)
    assert not (tmp_path / "evaluator-bundle").exists()
    assert not list(tmp_path.glob(".evaluator-bundle-*"))
