"""Preparation deadlines bound requests and local probes without changing execution policy."""
from __future__ import annotations

import copy
import json

import pytest
from test_automatic_solve_bundle import _fixture

from lunar_evolution import automatic_solve_bundle as automatic
from lunar_evolution import candidate_execution_runner, evaluator_bundle
from lunar_evolution.runtime import ModelRequestFailure, ModelRequestObservation


class Clock:
    value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def prepare(fixture, **options):
    controller, parent, contract, _ = fixture
    return automatic.prepare_automatic_solve_bundle(
        controller, parent.id, contract, timeout_seconds=3,
        evaluator_preparation_timeout_seconds=7,
        evaluator_preparation_wall_timeout_seconds=10, **options,
    )


def assert_failed(fixture, stage):
    controller, parent, _, runtime = fixture
    observation = automatic.automatic_bundle_preparation_status(controller.store, parent.id)
    assert observation["schema_version"] == "4"
    assert observation["error_category"] == "preparation_timeout"
    assert observation["recoverable"] is True and observation["stage"] == stage
    assert observation["wall_failure"] == {
        "schema_version": "1", "reason": "wall_timeout", "elapsed_ms": 10000,
        "wall_timeout_ms": 10000,
    }
    assert controller.store.get_run(parent.id).status.value == "running"
    assert not any(item["type"] == "bundle_profile_prepared" for item in controller.store.list_events(parent.id))
    assert not (parent.workspace / "evolution-run").exists()
    return observation, runtime


def test_remaining_wall_clips_each_request_and_process_preserving_profile(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    original = runtime.run
    requests, processes = [], []

    def request(prompt, workspace, timeout=None):
        requests.append(timeout)
        result = original(prompt, workspace, timeout)
        clock.advance(5 if len(requests) == 1 else 4)
        return result

    original_process = candidate_execution_runner._bounded_process_bytes

    def process(*args, **kwargs):
        processes.append(kwargs["timeout"])
        return original_process(*args, **kwargs)

    monkeypatch.setattr(runtime, "run", request)
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", process)
    prepare(fixture)
    assert requests == [7, 5]
    assert 3 in processes and 1 in processes and set(processes) == {3, 1}
    raw = (parent.workspace / "bundle-profile.json").read_bytes()
    profile = json.loads(raw)
    assert profile["timeout_seconds"] == profile["evaluator"]["timeout_seconds"] == 3
    assert b"preparation" not in raw
    start = next(row["payload"] for row in controller.store.list_events(parent.id)
                 if row["type"] == "bundle_preparation_started")
    assert start["preparation_budgets"] == {
        "candidate_timeout_seconds": 3, "request_timeout_seconds": 7, "wall_timeout_seconds": 10,
    }
    reference = _fixture(tmp_path / "reference")
    automatic.prepare_automatic_solve_bundle(reference[0], reference[1].id, reference[2], timeout_seconds=3)
    assert (reference[1].workspace / "bundle-profile.json").read_bytes() == raw


@pytest.mark.parametrize("expiry,stage,calls", [
    ("before_compiler", "evaluator_compile", (0, 0)),
    ("compiler", "evaluator_compile", (1, 0)),
    ("auditor", "evaluator_audit", (1, 1)),
    ("probe", "compiler_preflight", (1, 0)),
    ("profile", "profile_publish", (1, 1)),
])
def test_expiry_stops_before_next_request_or_publication(tmp_path, monkeypatch, expiry, stage, calls):
    fixture = _fixture(tmp_path)
    _, parent, _, runtime = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    original = runtime.run

    def request(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        if ((expiry == "compiler" and "frozen local evaluator bundle" in prompt)
                or (expiry == "auditor" and "adversarial evaluator auditor" in prompt)):
            clock.advance(10)
        return result

    monkeypatch.setattr(runtime, "run", request)
    if expiry == "before_compiler":
        original_prompt = evaluator_bundle._compiler_prompt

        def prompt(*args, **kwargs):
            result = original_prompt(*args, **kwargs)
            clock.advance(10)
            return result

        monkeypatch.setattr(evaluator_bundle, "_compiler_prompt", prompt)
    elif expiry == "probe":
        original_process = candidate_execution_runner._bounded_process_bytes

        def process(*args, **kwargs):
            result = original_process(*args, **kwargs)
            clock.advance(10)
            return result

        monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", process)
    elif expiry == "profile":
        original_profile = automatic._profile_payload

        def profile(*args, **kwargs):
            result = original_profile(*args, **kwargs)
            clock.value = 110
            return result

        monkeypatch.setattr(automatic, "_profile_payload", profile)
    with pytest.raises(automatic.AutomaticBundlePreparationError):
        prepare(fixture)
    assert_failed(fixture, stage)
    assert (runtime.bundle_calls, runtime.audit_calls) == calls
    assert not (parent.workspace / "bundle-profile.json").exists()


@pytest.mark.parametrize("boundary", ["profile_write", "artifact_registration"])
def test_publication_expiry_retains_verified_resumable_materials(tmp_path, monkeypatch, boundary):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    owner, name = ((automatic, "_write_profile") if boundary == "profile_write"
                   else (controller.store, "add_artifact"))
    original = getattr(owner, name)

    def expire(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.value = 110
        return result

    monkeypatch.setattr(owner, name, expire)
    with pytest.raises(automatic.AutomaticBundlePreparationError):
        prepare(fixture)
    assert_failed(fixture, "profile_publish")
    automatic.validate_automatic_solve_bundle(controller.store, parent.id)
    monkeypatch.setattr(owner, name, original)
    prepare(fixture)
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert automatic.automatic_bundle_preparation_status(controller.store, parent.id)["status"] == "prepared"
    rows = controller.store.list_artifacts(parent.id)
    assert len({row["path"] for row in rows}) == len(rows)


def test_wall_failure_preserves_typed_request_observation(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    runtime = fixture[3]
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)

    def failed_request(*_args, **_kwargs):
        clock.advance(10)
        error = ModelRequestFailure("private provider body", "transport_timeout")
        error.observation = ModelRequestObservation("open_response", 10000, 7000)
        raise error

    monkeypatch.setattr(runtime, "run", failed_request)
    with pytest.raises(automatic.AutomaticBundlePreparationError):
        prepare(fixture)
    observation, _ = assert_failed(fixture, "evaluator_compile")
    assert observation["request_failure"]["reason"] == "transport_timeout"
    assert observation["request_failure"]["request_observation"]["request_timeout_ms"] == 7000
    assert "private" not in json.dumps(observation)


@pytest.mark.parametrize("drift", ["input", "cancel", "terminal"])
def test_integrity_and_parent_state_take_precedence_over_expiry(tmp_path, monkeypatch, drift):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    original = runtime.run

    def request(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.advance(10)
        if drift == "input":
            (parent.workspace / "data/raw/orders.csv").write_bytes(b"id\nchanged-order\n")
        elif drift == "cancel":
            controller.store.cancel_run(parent.id)
        else:
            with controller.store._connect() as connection:
                connection.execute("UPDATE runs SET status = 'succeeded' WHERE id = ?", (parent.id,))
        return result

    monkeypatch.setattr(runtime, "run", request)
    with pytest.raises(automatic.AutomaticBundlePreparationError) as caught:
        prepare(fixture)
    observation = caught.value.preparation
    assert observation["recoverable"] is False and "wall_failure" not in observation
    assert observation["error_category"] == ("cancelled" if drift == "cancel" else "validation_error")


@pytest.mark.parametrize("wall", [True, 0, -1, float("nan"), float("inf"), 6, 86401])
def test_invalid_wall_budgets_do_not_start_attempt(tmp_path, wall):
    fixture = _fixture(tmp_path)
    controller, parent, contract, runtime = fixture
    before = controller.store.list_events(parent.id)
    with pytest.raises(automatic.EvolutionError, match="settings_invalid"):
        automatic.prepare_automatic_solve_bundle(
            controller, parent.id, contract, timeout_seconds=3,
            evaluator_preparation_timeout_seconds=7, evaluator_preparation_wall_timeout_seconds=wall,
        )
    assert controller.store.list_events(parent.id) == before
    assert runtime.bundle_calls == runtime.audit_calls == 0


@pytest.mark.parametrize("corruption", [
    "extra_detail", "elapsed_bool", "elapsed_negative", "elapsed_under_limit", "elapsed_unbounded",
    "limit_float", "limit_mismatch", "reason", "schema", "start_extra", "start_unbounded",
    "start_budget_bool", "start_budget_mismatch", "duplicate_start", "intervening_start", "outer_extra",
    "request_on_local_stage", "request_malformed",
])
def test_wall_status_rejects_malformed_or_unbound_diagnostics(tmp_path, monkeypatch, corruption):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    controller.store.append_event(parent.id, "evolution_requested", {
        "bundle_mode": "compiled", "timeout": 3, "evaluator_preparation_timeout": 7,
        "evaluator_preparation_wall_timeout": 10,
    })
    original = runtime.run

    def request(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.advance(10)
        return result

    monkeypatch.setattr(runtime, "run", request)
    with pytest.raises(automatic.AutomaticBundlePreparationError):
        prepare(fixture)
    events = [item for item in controller.store.list_events(parent.id)
              if item["type"].startswith("bundle_preparation_")]
    start, failed = events
    payload, started = copy.deepcopy(failed["payload"]), copy.deepcopy(start["payload"])
    detail = payload["wall_failure"]
    if corruption == "extra_detail":
        detail["private"] = "untrusted-private-text"
    elif corruption.startswith("elapsed_"):
        detail["elapsed_ms"] = {
            "elapsed_bool": True, "elapsed_negative": -1, "elapsed_under_limit": 9999,
            "elapsed_unbounded": 86400001,
        }[corruption]
    elif corruption == "limit_float":
        detail["wall_timeout_ms"] = 10000.0
    elif corruption == "limit_mismatch":
        detail["wall_timeout_ms"] = 9000
    elif corruption == "reason":
        detail["reason"] = "untrusted-private-text"
    elif corruption == "schema":
        payload["schema_version"] = "3"
    elif corruption == "start_extra":
        started["private"] = "untrusted-private-text"
    elif corruption == "start_unbounded":
        started.pop("preparation_budgets")
        started["schema_version"] = "1"
    elif corruption == "start_budget_bool":
        started["preparation_budgets"]["candidate_timeout_seconds"] = True
    elif corruption == "start_budget_mismatch":
        started["preparation_budgets"]["wall_timeout_seconds"] = 9
        detail["wall_timeout_ms"] = 9000
    elif corruption in {"duplicate_start", "intervening_start"}:
        extra = copy.deepcopy(started)
        if corruption == "intervening_start":
            extra["attempt_id"] = "preparation-" + "a" * 32
        controller.store.append_event(parent.id, "bundle_preparation_started", extra)
        controller.store.append_event(parent.id, "bundle_preparation_failed", payload)
    elif corruption == "outer_extra":
        payload["private"] = "untrusted-private-text"
    elif corruption == "request_on_local_stage":
        payload["stage"] = "compiler_preflight"
        payload["request_failure"] = {
            "schema_version": "1", "reason": "transport_timeout", "response_status": None,
            "request_observation": None, "transport_observation": None,
        }
    elif corruption == "request_malformed":
        payload["request_failure"] = {"private": "untrusted-private-text"}
    with controller.store._connect() as connection:
        for event, value in ((start, started), (failed, payload)):
            connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(value), event["id"]))
    observation = automatic.automatic_bundle_preparation_status(controller.store, parent.id)
    assert observation["error_category"] == "validation_error" and observation["recoverable"] is False
    assert "wall_failure" not in observation and "request_failure" not in observation
    assert "untrusted-private-text" not in json.dumps(observation)


def test_attempt_clock_starts_after_durable_start_record(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, _ = fixture
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    original = controller.store.append_event

    def append(run_id, kind, payload, **kwargs):
        result = original(run_id, kind, payload, **kwargs)
        if kind == "bundle_preparation_started":
            clock.advance(20)
        return result

    monkeypatch.setattr(controller.store, "append_event", append)
    prepare(fixture)
    assert automatic.automatic_bundle_preparation_status(controller.store, parent.id)["status"] == "prepared"


@pytest.mark.parametrize("field", ["timeout_seconds", "evaluator_preparation_timeout_seconds"])
def test_huge_timeout_rejected_before_float_conversion(tmp_path, field):
    controller, parent, contract, runtime = _fixture(tmp_path)
    before = controller.store.list_events(parent.id)
    with pytest.raises(automatic.EvolutionError, match="settings_invalid"):
        automatic.prepare_automatic_solve_bundle(controller, parent.id, contract, **{field: 10 ** 1000})
    assert controller.store.list_events(parent.id) == before
    assert runtime.bundle_calls == runtime.audit_calls == 0


def test_start_binding_does_not_accept_boolean_policy_as_one_second():
    parent, attempt = "parent", "preparation-" + "a" * 32
    started = automatic._observation(
        parent, attempt, status="started", stage="preparation",
        preparation_budgets={"candidate_timeout_seconds": 1,
                             "request_timeout_seconds": 1, "wall_timeout_seconds": 2},
    )
    policy = {"bundle_mode": "compiled", "timeout": True,
              "evaluator_preparation_timeout": 1, "evaluator_preparation_wall_timeout": 2}
    assert not automatic._valid_start(started, parent, attempt, [
        {"type": "evolution_requested", "payload": policy},
    ])
