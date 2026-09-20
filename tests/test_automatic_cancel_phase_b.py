"""Focused Phase B cancellation and process-registration regression tests."""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.automatic_solve_lifecycle import SolveExecutionCancelled
from famou.config import Config
from famou.controller import LocalController
from famou.models import RunStatus
from famou.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from famou.runtime import MockRuntime
from famou.store import Store


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "phase-b-cancel-fixture",
            "problem_type": "routing",
            "statement": "Find a valid route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Serve every item.",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
            ],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {"strategy": "population", "max_rounds": 2, "stagnation_rounds": 2},
        }
    )


def _automatic_pair(tmp_path: Path) -> tuple[LocalController, object, object, AlgorithmProblemContract]:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    parent = controller.store.create_run("automatic parent", tmp_path / "parent")
    child = controller.store.create_run("automatic child", tmp_path / "child")
    contract = _contract()
    digest = contract.digest()
    controller.store.append_event(
        parent.id,
        "evolution_requested",
        {"bundle_mode": "compiled", "automatic_lifecycle_version": 1},
    )
    controller.store.append_event(
        parent.id,
        "evolution_linked",
        {"evolution_run_id": child.id, "strategy": "population", "contract_sha256": digest},
    )
    controller.store.append_event(
        child.id,
        "evolution_parent_linked",
        {"parent_run_id": parent.id, "contract_sha256": digest},
    )
    # The production path obtains this from the current plan.  Keep the test focused on
    # cancellation/link authority without requiring a full conversational compilation.
    controller._algorithm_contract = lambda _run: contract  # type: ignore[method-assign]
    return controller, parent, child, contract


def _cleaned(registration):
    return ProcessCleanupResult(
        registration.label,
        registration.pid,
        registration.pgid,
        ProcessCleanupStatus.CLEANED,
    )


def test_verified_automatic_cancel_cancels_child_and_all_registered_attempts(tmp_path, monkeypatch):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    parent_task = controller.store.list_tasks(parent.id)[0]
    child_task = controller.store.list_tasks(child.id)[0]
    parent_attempt = controller.store.claim_task(parent_task.id, "fixture")
    child_attempt = controller.store.claim_task(child_task.id, "fixture")
    assert parent_attempt is not None and child_attempt is not None
    controller.store.set_runner_process(parent.id, 101, 201)
    controller.store.set_runner_process(child.id, 102, 202)
    controller.store.set_attempt_process(parent_attempt.id, 103, 203)
    controller.store.set_attempt_process(child_attempt.id, 104, 204)

    cleaned: list[str] = []
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        cleaned.append(reg.label) or _cleaned(reg) for reg in regs
    ))
    monkeypatch.setattr(controller, "_terminate_process_group", lambda *_args: pytest.fail("legacy path used"))

    assert controller.cancel(parent.id)
    assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
    assert controller.store.get_run(child.id).status is RunStatus.CANCELLED
    assert {f"run:{parent.id}", f"run:{child.id}", f"attempt:{parent_attempt.id}", f"attempt:{child_attempt.id}"} == set(cleaned)
    assert controller.store.get_run(parent.id).runner_pid is None
    assert controller.store.get_run(child.id).runner_pid is None
    assert controller.store.get_attempt(parent_attempt.id).pid is None
    assert controller.store.get_attempt(child_attempt.id).pid is None


@pytest.mark.parametrize("contract_ready", [False, True], ids=["intake", "preparation"])
def test_automatic_cancel_before_child_link_cleans_parent_process(tmp_path, monkeypatch, contract_ready):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    if not contract_ready:
        controller._algorithm_contract = lambda _run: None
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'evolution_linked'", (parent.id,))
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'evolution_parent_linked'", (child.id,))
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "preparation-fixture")
    assert attempt is not None
    controller.store.set_attempt_process(attempt.id, 103, 203)
    cleaned = []
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        cleaned.append(reg.label) or _cleaned(reg) for reg in regs
    ))

    assert controller.cancel(parent.id)

    assert cleaned == [f"attempt:{attempt.id}"]
    assert controller.store.get_attempt(attempt.id).pid is None
    assert controller.store.get_run(child.id).status is RunStatus.PENDING


def test_automatic_cancel_cleans_attempts_before_their_controller_runners(tmp_path, monkeypatch):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    attempts = []
    for index, run in enumerate((parent, child), 1):
        task = controller.store.list_tasks(run.id)[0]
        attempt = controller.store.claim_task(task.id, "fixture")
        assert attempt is not None
        attempts.append(attempt)
        controller.store.set_attempt_process(attempt.id, 100 + index, 200 + index)
        controller.store.set_runner_process(run.id, 300 + index, 400 + index)
    cleaned = []
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        cleaned.append(reg.label) or _cleaned(reg) for reg in regs
    ))

    assert controller.cancel(parent.id)

    attempt_positions = [cleaned.index(f"attempt:{attempt.id}") for attempt in attempts]
    runner_positions = [cleaned.index(f"run:{run.id}") for run in (parent, child)]
    assert max(attempt_positions) < min(runner_positions)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda parent, child: {"automatic_lifecycle_version": 2},
        lambda parent, child: {"automatic_lifecycle_version": True},
        lambda parent, child: {"automatic_lifecycle_version": 1.0},
        lambda parent, child: {"bundle_mode": "legacy"},
        lambda parent, child: {"link": "parent"},
        lambda parent, child: {"link": "child"},
        lambda parent, child: {"contract": "wrong"},
    ],
    ids=["marker", "boolean_marker", "float_marker", "bundle_mode", "parent_link", "child_link", "contract"],
)
def test_automatic_cancel_fails_closed_on_marker_link_or_contract_mismatch(
    tmp_path, monkeypatch, mutation,
):
    controller, parent, child, contract = _automatic_pair(tmp_path)
    change = mutation(parent, child)
    if "automatic_lifecycle_version" in change or "bundle_mode" in change:
        payload = {"bundle_mode": "compiled", "automatic_lifecycle_version": 1}
        payload.update(change)
        events = controller.store.list_events(parent.id)
        request_id = next(item["id"] for item in events if item["type"] == "evolution_requested")
        with controller.store._connect() as connection:
            connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), request_id))
    elif change.get("link") == "parent":
        controller.store.append_event(
            parent.id,
            "evolution_linked",
            {"evolution_run_id": "other-child", "strategy": "population", "contract_sha256": contract.digest()},
        )
    elif change.get("link") == "child":
        controller.store.append_event(
            child.id,
            "evolution_parent_linked",
            {"parent_run_id": "other-parent", "contract_sha256": contract.digest()},
        )
    else:
        controller.store.append_event(
            child.id,
            "evolution_parent_linked",
            {"parent_run_id": parent.id, "contract_sha256": "0" * 64},
        )
    controller.store.set_runner_process(parent.id, 111, 211)
    controller.store.set_runner_process(child.id, 112, 212)
    terminated: list[tuple[int | None, int | None]] = []
    monkeypatch.setattr(controller, "_terminate_process_group", lambda pid, pgid: terminated.append((pid, pgid)))
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda _regs: pytest.fail("child cleanup granted"))

    assert controller.cancel(parent.id)
    assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
    # A present but invalid lifecycle marker, or any malformed reciprocal evidence, grants
    # neither child cancellation authority nor process-signal authority.
    assert controller.store.get_run(child.id).status is RunStatus.PENDING
    assert terminated == []
    assert controller.store.get_run(parent.id).runner_pid == 111
    assert controller.store.get_run(child.id).runner_pid == 112


def test_legacy_cancel_keeps_parent_only_process_behavior(tmp_path, monkeypatch):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    events = controller.store.list_events(parent.id)
    request_id = next(item["id"] for item in events if item["type"] == "evolution_requested")
    with controller.store._connect() as connection:
        connection.execute(
            "UPDATE events SET payload = ? WHERE id = ?",
            (json.dumps({"bundle_mode": "compiled"}), request_id),
        )
    controller.store.set_runner_process(parent.id, 111, 211)
    controller.store.set_runner_process(child.id, 112, 212)
    terminated: list[tuple[int | None, int | None]] = []
    monkeypatch.setattr(controller, "_terminate_process_group", lambda pid, pgid: terminated.append((pid, pgid)))

    assert controller.cancel(parent.id)
    assert controller.store.get_run(child.id).status is RunStatus.PENDING
    assert terminated == [(111, 211)]


def test_child_terminal_state_is_not_rewritten_by_parent_cancel(tmp_path, monkeypatch):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (RunStatus.SUCCEEDED.value, child.id))
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(_cleaned(reg) for reg in regs))
    monkeypatch.setattr(controller, "_terminate_process_group", lambda *_args: pytest.fail("legacy path used"))
    assert controller.cancel(parent.id)
    assert controller.store.get_run(child.id).status is RunStatus.SUCCEEDED


def test_conditional_process_clear_preserves_reused_registration(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("runner")
    assert store.set_runner_process(run.id, 301, 401)
    assert not store.clear_runner_process(run.id, 302, 402)
    assert store.get_run(run.id).runner_pid == 301
    assert not store.clear_runner_process(run.id, 301, 402)
    assert store.get_run(run.id).runner_pgid == 401
    assert store.clear_runner_process(run.id, 301, 401)

    task = store.list_tasks(run.id)[0]
    attempt = store.claim_task(task.id, "fixture")
    assert attempt is not None
    assert store.set_attempt_process(attempt.id, 501, 601)
    assert not store.clear_attempt_process(attempt.id, 502, 602)
    assert store.get_attempt(attempt.id).pid == 501
    assert not store.clear_attempt_process(attempt.id, 501, 602)
    assert store.get_attempt(attempt.id).pgid == 601
    assert store.clear_attempt_process(attempt.id, 501, 601)


@pytest.mark.parametrize("side,field,value", [
    ("parent", "contract_sha256", "0" * 64),
    ("parent", "strategy", "sequential"),
    ("child", "contract_sha256", "0" * 64),
    ("child", "parent_run_id", "different-parent"),
])
def test_single_inconsistent_link_cannot_grant_child_cancel_authority(
    tmp_path, monkeypatch, side, field, value,
):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    run_id = parent.id if side == "parent" else child.id
    kind = "evolution_linked" if side == "parent" else "evolution_parent_linked"
    link = next(event for event in controller.store.list_events(run_id) if event["type"] == kind)
    payload = {**link["payload"], field: value}
    with controller.store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), link["id"]))
    controller.store.set_runner_process(child.id, 112, 212)
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda _regs: pytest.fail("cleanup granted"))

    assert controller.cancel(parent.id)
    assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
    assert controller.store.get_run(child.id).status is RunStatus.PENDING
    assert controller.store.get_run(child.id).runner_pid == 112


@pytest.mark.parametrize("payload", [
    {},
    None,
    {"bundle_mode": "compiled", "automatic_lifecycle_version": 1},
], ids=["empty", "malformed", "duplicate_marker"])
def test_lifecycle_request_history_cannot_downgrade_into_legacy_cleanup(tmp_path, monkeypatch, payload):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    controller.store.append_event(parent.id, "evolution_requested", payload)
    controller.store.set_runner_process(parent.id, 111, 211)
    controller.store.set_runner_process(child.id, 112, 212)
    monkeypatch.setattr(controller, "_terminate_process_group", lambda *_args: pytest.fail("legacy cleanup granted"))
    monkeypatch.setattr(controller, "_cancel_active_callbacks", lambda *_args: pytest.fail("runtime cancel granted"))
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda _regs: pytest.fail("cleanup granted"))

    assert controller.cancel(parent.id)

    assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
    assert controller.store.get_run(child.id).status is RunStatus.PENDING
    assert controller.store.get_run(parent.id).runner_pid == 111
    assert controller.store.get_run(child.id).runner_pid == 112


def test_process_registered_after_cancel_is_immediately_cleaned(tmp_path, monkeypatch):
    controller, parent, _, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    observe, release = controller.attempt_process_observers(parent.id, attempt.id)
    cleaned = []
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        cleaned.append((reg.label, reg.pid, reg.pgid)) or _cleaned(reg) for reg in regs
    ))
    assert controller.cancel(parent.id)
    cleaned.clear()

    observe(501, 601)

    assert cleaned == [(f"attempt:{attempt.id}", 501, 601)]
    assert controller.store.get_attempt(attempt.id).pid is None
    release(501, 601)
    assert controller.store.get_attempt(attempt.id).pid is None


def test_failed_cancel_cleanup_retains_registration_for_later_recovery(tmp_path, monkeypatch):
    controller, parent, _, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    controller.store.set_attempt_process(attempt.id, 501, 601)
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        ProcessCleanupResult(reg.label, reg.pid, reg.pgid, ProcessCleanupStatus.KILL_FAILED, alive_after=True)
        for reg in regs
    ))

    assert controller.cancel(parent.id)

    assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
    assert controller.store.get_attempt(attempt.id).pid == 501
    assert controller.store.get_attempt(attempt.id).pgid == 601


def test_process_observer_release_cannot_clear_newer_registration(tmp_path):
    controller, parent, _, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    observe, release = controller.attempt_process_observers(parent.id, attempt.id)
    observe(501, 601)
    assert controller.store.get_attempt(attempt.id).pid == 501
    controller.store.set_attempt_process(attempt.id, 501, 602)

    release(501, 601)

    assert controller.store.get_attempt(attempt.id).pid == 501
    assert controller.store.get_attempt(attempt.id).pgid == 602


def test_budget_failure_cleans_retained_processes_after_attempt_state_changes(tmp_path, monkeypatch):
    controller, parent, _, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    controller.store.set_attempt_process(attempt.id, 501, 601)
    assert controller.store.fail_budget(parent.id, "solve_wall_timeout", 10.0, 10.0, "deadline reached")
    cleaned = []
    monkeypatch.setattr("famou.controller.cleanup_registered_processes", lambda regs: tuple(
        cleaned.append(reg.label) or _cleaned(reg) for reg in regs
    ))

    controller.cleanup_automatic_solve(parent.id)

    assert cleaned == [f"attempt:{attempt.id}"]
    assert controller.store.get_attempt(attempt.id).pid is None
    assert controller.store.get_run(parent.id).status is RunStatus.FAILED


def test_automatic_cli_registers_probe_candidate_and_evaluator_on_owning_attempt(
    tmp_path, monkeypatch, capsys,
):
    from collections import Counter

    from test_conversational_automatic_bundle import automatic_setup

    from famou import candidate_evaluation, candidate_execution_runner, cli

    _, args = automatic_setup(tmp_path, monkeypatch)
    original = candidate_execution_runner._bounded_process_bytes
    events = []

    def registrations(store, pid, pgid):
        with store._connect() as connection:
            return [row["run_id"] for row in connection.execute(
                "SELECT tasks.run_id FROM attempts JOIN tasks ON tasks.id = attempts.task_id "
                "WHERE attempts.pid = ? AND attempts.pgid = ?", (pid, pgid),
            ).fetchall()]

    def run(command, **kwargs):
        stage = ("probe" if Path(kwargs["cwd"]).parent.name in {".compiler-preflight", ".audit-preflight"}
                 else "evaluator" if command[-1] == "request.json" else "candidate")
        observe, release = kwargs.get("process_observer"), kwargs.get("process_released")
        store = Store(tmp_path / "home/state.db")
        parent = store.get_run_by_workspace(tmp_path / "conversation")
        assert parent is not None
        if stage == "probe":
            expected_owner = parent.id
        else:
            links = [event for event in store.list_events(parent.id) if event["type"] == "evolution_linked"]
            assert len(links) == 1
            expected_owner = links[0]["payload"]["evolution_run_id"]

        def observed(pid, pgid):
            if observe is not None:
                observe(pid, pgid)
            events.append((stage, "observed", expected_owner, registrations(store, pid, pgid)))

        def released(pid, pgid):
            if release is not None:
                release(pid, pgid)
            events.append((stage, "released", expected_owner, registrations(store, pid, pgid)))

        kwargs.update(process_observer=observed, process_released=released)
        return original(command, **kwargs)

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", run)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", run)

    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"
    observed = [event for event in events if event[1] == "observed"]
    released = [event for event in events if event[1] == "released"]
    assert Counter(event[0] for event in observed) == {"probe": 6, "candidate": 4, "evaluator": 4}
    assert len(observed) == len(released)
    assert all(owners == [expected] for _, _, expected, owners in observed)
    assert all(owners == [] for _, _, _, owners in released)


def test_parent_cancel_stops_real_registered_child_process(tmp_path):
    from famou.candidate_execution_runner import _bounded_process_bytes

    controller, parent, child, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(child.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    observe, release = controller.attempt_process_observers(child.id, attempt.id, parent_id=parent.id)
    ready = tmp_path / "process-ready"
    started = threading.Event()
    processes = []
    results = []
    errors = []

    def observed(pid, pgid):
        observe(pid, pgid)
        processes.append((pid, pgid))
        started.set()

    def execute():
        try:
            results.append(_bounded_process_bytes(
                [str(Path(sys.executable).resolve()), "-I", "-c",
                 "import sys, time; from pathlib import Path; Path(sys.argv[1]).touch(); time.sleep(10)",
                 str(ready)],
                cwd=str(tmp_path.resolve()), environment={}, timeout=10,
                output_limit=1024, capture_limit=1024,
                process_observer=observed, process_released=release,
            ))
        except BaseException as exc:  # noqa: BLE001 - expose thread failures to the test owner
            errors.append(exc)

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    try:
        assert started.wait(3)
        deadline = time.monotonic() + 3
        while not ready.exists() and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        assert controller.cancel(parent.id)
        thread.join(timeout=3)

        assert not thread.is_alive()
        assert errors == []
        assert len(results) == 1 and results[0][2] == "failed"
        assert controller.store.get_run(parent.id).status is RunStatus.CANCELLED
        assert controller.store.get_run(child.id).status is RunStatus.CANCELLED
        assert controller.store.get_attempt(attempt.id).pid is None
        with pytest.raises(ProcessLookupError):
            os.getpgid(processes[0][0])
    finally:
        for pid, pgid in processes:
            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        thread.join(timeout=3)


@pytest.mark.parametrize("parent_terminal", [False, True], ids=["delivery_pending", "delivered"])
def test_completed_automatic_child_resume_preserves_result_without_starting_work(tmp_path, parent_terminal):
    from test_bundle_population import build_context

    context = build_context(tmp_path)
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    parent = controller.store.create_run("automatic parent", tmp_path / "parent")
    child = controller.create_evolution_run(context.contract, workspace=context.workspace)
    digest = context.contract.digest()
    controller._algorithm_contract = lambda _run: context.contract
    controller.store.append_event(parent.id, "evolution_requested", {
        "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
    })
    controller.store.append_event(parent.id, "evolution_linked", {
        "evolution_run_id": child.id, "strategy": "population", "contract_sha256": digest,
    })
    controller.store.append_event(child.id, "evolution_parent_linked", {
        "parent_run_id": parent.id, "contract_sha256": digest,
    })
    settled, result = controller.run_evolution(
        child.id, context.contract, context.generate, context.evaluate, context.config,
        bundle_pipeline=context.bundle_pipeline, automatic_parent_id=parent.id,
    )
    assert settled.status is RunStatus.SUCCEEDED
    if parent_terminal:
        with controller.store._connect() as connection:
            connection.execute("UPDATE runs SET status = ? WHERE id = ?", (RunStatus.SUCCEEDED.value, parent.id))
    before = {path.relative_to(context.workspace): path.read_bytes()
              for path in context.workspace.rglob("*") if path.is_file()}
    events = controller.store.list_events(child.id)

    def forbidden(*args, **kwargs):
        pytest.fail("terminal child resumed execution")

    resumed, resumed_result = controller.run_evolution(
        child.id, context.contract, forbidden, forbidden, context.config,
        bundle_pipeline=context.bundle_pipeline, automatic_parent_id=parent.id, resume=True,
    )

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed_result == result
    assert controller.store.list_events(child.id) == events
    assert before == {path.relative_to(context.workspace): path.read_bytes()
                      for path in context.workspace.rglob("*") if path.is_file()}


def test_new_launch_cannot_replace_registration_retained_after_failed_cleanup(tmp_path, monkeypatch):
    controller, parent, _, _ = _automatic_pair(tmp_path)
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    observe, release = controller.attempt_process_observers(parent.id, attempt.id)
    observe(501, 601)
    cleaned = []

    def cleanup(registrations):
        results = []
        for registration in registrations:
            cleaned.append((registration.label, registration.pid, registration.pgid))
            results.append(
                ProcessCleanupResult(registration.label, registration.pid, registration.pgid,
                                     ProcessCleanupStatus.KILL_FAILED, alive_after=True)
                if registration.pid == 501 else _cleaned(registration)
            )
        return tuple(results)

    monkeypatch.setattr("famou.controller.cleanup_registered_processes", cleanup)

    observe(502, 602)

    assert cleaned == [(f"attempt:{attempt.id}", 501, 601), ("unregistered-launch", 502, 602)]
    retained = controller.store.get_attempt(attempt.id)
    assert (retained.pid, retained.pgid) == (501, 601)
    release(502, 602)
    retained = controller.store.get_attempt(attempt.id)
    assert (retained.pid, retained.pgid) == (501, 601)


@pytest.mark.parametrize("with_parent", [False, True], ids=["parent_stage", "child_stage"])
def test_cleanup_guard_fails_owned_runs_and_preserves_unreleased_process(tmp_path, monkeypatch, with_parent):
    controller, parent, child, _ = _automatic_pair(tmp_path)
    if with_parent:
        orchestration = controller.store.ensure_orchestration_task(
            parent.id, title="Automatic solve orchestration", prompt="evolve and deliver",
        )
        assert controller.store.claim_orchestration_task(orchestration.id, "automatic-solve") is not None
    current = child if with_parent else parent
    task = controller.store.list_tasks(current.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    controller.store.set_attempt_process(attempt.id, 501, 601)
    cleaned = []

    def cleanup(registrations):
        return tuple(
            cleaned.append((registration.label, registration.pid, registration.pgid))
            or ProcessCleanupResult(registration.label, registration.pid, registration.pgid,
                                    ProcessCleanupStatus.KILL_FAILED, alive_after=True)
            for registration in registrations
        )

    monkeypatch.setattr("famou.controller.cleanup_registered_processes", cleanup)

    with pytest.raises(SolveExecutionCancelled):
        controller.ensure_attempt_process_released(
            current.id, attempt.id, parent_id=parent.id if with_parent else None,
        )

    assert (f"attempt:{attempt.id}", 501, 601) in cleaned
    assert controller.store.get_run(current.id).status is RunStatus.FAILED
    assert controller.store.get_run(parent.id).status is RunStatus.FAILED
    retained = controller.store.get_attempt(attempt.id)
    assert (retained.pid, retained.pgid) == (501, 601)
    assert not controller.cancel(current.id)
    assert not controller.cancel(parent.id)
    assert controller.store.get_run(current.id).status is RunStatus.FAILED
    assert controller.store.get_run(parent.id).status is RunStatus.FAILED
    retained = controller.store.get_attempt(attempt.id)
    assert (retained.pid, retained.pgid) == (501, 601)
