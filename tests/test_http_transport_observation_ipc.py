"""Strict, bounded milestone progress and historical transport framing."""

from dataclasses import FrozenInstanceError, asdict

import pytest
from test_http_transport_deadline import frames, success_frames

from famou import http_transport as h


def milestone(name, index, elapsed=10):
    return {"kind": "milestone", "last_milestone": name,
            "http_exchange_index": index, "elapsed_ms": elapsed}


def details(hops=1):
    return [milestone("worker_ready", 0, 0)] + [
        milestone(name, index, index * 10 + offset)
        for index in range(1, hops + 1)
        for offset, name in enumerate((
            "prepare_request", "connect", "send_request",
            "wait_response_headers", "response_headers_received",
        ))
    ]


def detailed_success(hops=1):
    values = success_frames()
    return [values[0], *details(hops), *values[1:]]


def test_snapshot_is_frozen_and_old_transport_constructors_are_compatible():
    response = h._decode_result(frames(*success_frames()))
    assert response == h.TransportResponse(200, b"{}")
    assert response.observation is None and h.TransportFailure().observation is None
    value = h.TransportObservation("worker_ready", 0, 0)
    with pytest.raises(FrozenInstanceError):
        value.elapsed_ms = 1


@pytest.mark.parametrize("hops", [1, 2, 11])
def test_success_keeps_last_timestamp_and_counts_http_exchanges(hops):
    response = h._decode_result(frames(*detailed_success(hops)))
    assert response.status == 200 and response.body == b"{}"
    assert response.observation == h.TransportObservation(
        "response_headers_received", hops, hops * 10 + 4,
    )


@pytest.mark.parametrize("count", range(1, 7))
def test_deadline_retains_only_complete_milestone_prefix(count):
    values = [success_frames()[0], *details()[:count]]
    raw = frames(*values)
    error = h._deadline_failure(raw)
    expected = {key: value for key, value in values[-1].items() if key != "kind"}
    assert asdict(error.observation) == expected
    assert (error.reason, error.phase, error.status) == ("transport_timeout", "open_response", None)
    assert h._deadline_failure(raw + b'{"kind":"milestone"').observation == error.observation


@pytest.mark.parametrize("phase,status,reason", [
    ("read_response_body", 200, "transport_timeout"),
    ("read_http_error_body", 503, "http_error"),
])
def test_deadline_keeps_final_body_classification_and_never_late_success(phase, status, reason):
    values = detailed_success()
    values[-2].update(phase=phase, status=status)
    raw = frames(*values[:-1])
    error = h._deadline_failure(raw + frames(values[-1]))
    assert (error.phase, error.status, error.reason) == (phase, status, reason)
    assert error.observation.last_milestone == "response_headers_received"


@pytest.mark.parametrize("cause,reason", [("timeout", "transport_timeout"), ("os_error", "transport_error")])
def test_terminal_failure_keeps_observation(cause, reason):
    values = [success_frames()[0], *details()[:-1], {
        "kind": "terminal", "outcome": "failure", "reason": reason,
        "cause": cause, "status": None, "body": "",
    }]
    with pytest.raises(h.TransportFailure) as caught:
        h._decode_result(frames(*values))
    assert caught.value.observation.last_milestone == "wait_response_headers"
    assert caught.value.reason == reason and caught.value.phase == "open_response"


@pytest.mark.parametrize("mutation", [
    "before_phase", "missing_ready", "repeated_ready", "missing_connect", "reversed",
    "index_bool", "index_float", "index_zero", "index_skip", "index_limit", "ready_index",
    "elapsed_bool", "elapsed_float", "elapsed_negative", "elapsed_limit", "elapsed_backwards",
    "elapsed_nan", "unknown_name", "missing_field", "extra_field", "wrong_kind",
    "after_body", "early_body", "duplicate", "unavailable_extra", "after_unavailable",
    "repeated_unavailable", "oversized", "partial_final",
])
def test_malformed_detail_cannot_be_accepted_as_success(mutation):
    values = detailed_success()
    if mutation == "before_phase":
        values[0], values[1] = values[1], values[0]
    elif mutation == "missing_ready":
        del values[1]
    elif mutation == "repeated_ready":
        values.insert(2, values[1])
    elif mutation == "missing_connect":
        del values[3]
    elif mutation == "reversed":
        values[3], values[4] = values[4], values[3]
    elif mutation.startswith("index_"):
        values[3]["http_exchange_index"] = {
            "index_bool": True, "index_float": 1.0, "index_zero": 0,
            "index_skip": 2, "index_limit": 257,
        }[mutation]
    elif mutation == "ready_index":
        values[1]["http_exchange_index"] = 1
    elif mutation.startswith("elapsed_"):
        values[3]["elapsed_ms"] = {
            "elapsed_bool": True, "elapsed_float": 1.5, "elapsed_negative": -1,
            "elapsed_limit": 10**12 + 1, "elapsed_backwards": 9, "elapsed_nan": float("nan"),
        }[mutation]
    elif mutation == "unknown_name":
        values[3]["last_milestone"] = "PRIVATE-FIXTURE-TEXT"
    elif mutation == "missing_field":
        del values[3]["elapsed_ms"]
    elif mutation == "extra_field":
        values[3]["endpoint"] = "PRIVATE-FIXTURE-TEXT"
    elif mutation == "wrong_kind":
        values[3]["kind"] = "PRIVATE-FIXTURE-TEXT"
    elif mutation == "after_body":
        values[-2], values[-3] = values[-3], values[-2]
    elif mutation == "early_body":
        values[4:7] = []
    elif mutation == "unavailable_extra":
        values[3] = {"kind": "observation_unavailable", "error": "PRIVATE-FIXTURE-TEXT"}
    elif mutation == "after_unavailable":
        values.insert(3, {"kind": "observation_unavailable"})
    elif mutation == "repeated_unavailable":
        values[3:7] = [{"kind": "observation_unavailable"}] * 2
    elif mutation == "oversized":
        values[3]["elapsed_ms"] = "x" * 600
    raw = frames(*values)
    if mutation == "duplicate":
        raw = raw.replace(b'"elapsed_ms": 11', b'"elapsed_ms": 11, "elapsed_ms": 12')
    elif mutation == "partial_final":
        raw = raw[:-1]
    with pytest.raises((ValueError, TypeError)):
        h._decode_result(raw)


def test_invalid_complete_deadline_progress_discards_detail():
    raw = frames(success_frames()[0], *details()[:4], milestone("connect", 2))
    error = h._deadline_failure(raw)
    assert error.observation is None
    assert error.phase == "open_response" and error.reason == "transport_timeout"


def test_detail_limit_discards_snapshot_but_preserves_transport_result(monkeypatch):
    output = []
    monkeypatch.setattr(h, "_emit", output.append)
    monkeypatch.setattr(h, "monotonic", lambda: 1)
    emitter = h._MilestoneEmitter(0)
    # More HTTP hops than native urllib allows: instrumentation still must not impose a limit.
    for value in details(60):
        emitter.emit(value["last_milestone"], value["http_exchange_index"])
    assert len(output) == h.MAX_TRANSPORT_MILESTONES + 1
    assert output[-1] == {"kind": "observation_unavailable"}
    values = success_frames()
    result = h._decode_result(frames(values[0], *output, *values[1:]))
    assert result == h.TransportResponse(200, b"{}")
    failure = h._deadline_failure(frames(values[0], *output))
    assert failure.observation is None and failure.reason == "transport_timeout"


def test_missing_explicit_limit_and_extra_progress_are_rejected():
    values = [success_frames()[0], *details(52), *success_frames()[1:]]
    with pytest.raises(ValueError):
        h._decode_result(frames(*values))


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), -1, 1e100, None])
def test_unusable_observation_clock_discards_only_optional_detail(monkeypatch, clock):
    output = []
    monkeypatch.setattr(h, "_emit", output.append)
    monkeypatch.setattr(h, "monotonic", lambda: clock)
    emitter = h._MilestoneEmitter(0)
    emitter.emit("worker_ready", 0)
    emitter.emit("prepare_request", 1)
    assert output == [{"kind": "observation_unavailable"}]
    values = success_frames()
    assert h._decode_result(frames(values[0], *output, *values[1:])).observation is None


def test_observation_elapsed_uses_parent_start_and_discards_clock_regression(monkeypatch):
    output = []
    times = iter([20.625, 20.125])
    monkeypatch.setattr(h, "_emit", output.append)
    monkeypatch.setattr(h, "monotonic", lambda: next(times))
    emitter = h._MilestoneEmitter(20)
    emitter.emit("worker_ready", 0)
    emitter.emit("prepare_request", 1)
    assert output == [milestone("worker_ready", 0, 625), {"kind": "observation_unavailable"}]


def test_failed_observation_clock_does_not_mask_native_request_outcome(monkeypatch):
    output = []

    def failed_clock():
        raise RuntimeError("PRIVATE-FIXTURE-TEXT")

    monkeypatch.setattr(h, "_emit", output.append)
    monkeypatch.setattr(h, "monotonic", failed_clock)
    emitter = h._MilestoneEmitter(0)
    emitter.emit("worker_ready", 0)
    emitter.emit("prepare_request", 1)
    assert output == [{"kind": "observation_unavailable"}]
    values = success_frames()
    assert h._decode_result(frames(values[0], *output, *values[1:])) == h.TransportResponse(200, b"{}")
