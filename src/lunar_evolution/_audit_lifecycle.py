"""Read retained automatic-solve lifecycle state without changing it.

A verified result covers durable identities and ordering only. The caller must separately
validate native delivery bytes before treating the delivery event as successful acceptance.
"""
from __future__ import annotations

import re
import sqlite3

from ._audit_snapshot import AuditSnapshotError, AuditStore, audit_events

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
_STAGES = frozenset({
    "contract", "preparation", "candidate_generation", "candidate_execution",
    "evaluation", "selection", "delivery", "solve",
})
_STATES = frozenset({"active", "awaiting_input", "terminal", "inactive"})
_REASONS = frozenset({
    None, "completed", "cancelled", "solve_wall_timeout", "failed", "interrupted",
    "awaiting_input", "preparation_recoverable",
})
_FAILURES = frozenset({"run_cancelled", "run_failed", "budget_exceeded"})


def _result(status, reason=None):
    return {"status": status, "reason": reason}


def audit_parent_lifecycle(
    store: AuditStore,
    *,
    parent_id: str,
    child_id: str,
    orchestration_task_id: str,
    solve_execution_id: str,
    contract_sha256: str,
) -> dict:
    """Audit one 3,000-second automatic solve's retained lifecycle.

    Unknown/missing observations remain unverifiable. Identity disagreement, duplicate slots,
    early success, or an earlier failure followed by success are failures. SQLite insertion
    sequence establishes ordering; timestamps and current status never replace terminal history.
    """
    if (not isinstance(store, AuditStore)
            or any(type(value) is not str or _ID.fullmatch(value) is None
                   for value in (parent_id, child_id, orchestration_task_id, solve_execution_id))
            or parent_id == child_id
            or type(contract_sha256) is not str or _SHA.fullmatch(contract_sha256) is None):
        return _result("failed", "lifecycle_request_invalid")
    try:
        return _inspect(
            store, parent_id, child_id, orchestration_task_id, solve_execution_id, contract_sha256,
        )
    except (AuditSnapshotError, sqlite3.Error, OSError, TypeError, ValueError, KeyError, AttributeError):
        return _result("unverifiable", "lifecycle_snapshot_invalid")


def _inspect(store, parent_id, child_id, task_id, execution_id, contract_digest):
    events = audit_events(store, parent_id, child_id)
    parent_events = [event for event in events if event["run_id"] == parent_id]
    child_events = [event for event in events if event["run_id"] == child_id]
    parent, child = store.get_run(parent_id), store.get_run(child_id)
    if parent is None or child is None:
        return _result("unverifiable", "lifecycle_run_missing")
    for own, kind, payload in (
        (parent_events, "evolution_linked", {
            "evolution_run_id": child_id, "contract_sha256": contract_digest,
            "strategy": "population",
        }),
        (child_events, "evolution_parent_linked", {
            "parent_run_id": parent_id, "contract_sha256": contract_digest,
        }),
    ):
        links = [event for event in own if event["type"] == kind]
        if not links:
            return _result("unverifiable", "lifecycle_link_missing")
        if len(links) != 1 or links[0]["task_id"] is not None or links[0]["payload"] != payload:
            return _result("failed", "lifecycle_link_mismatch")

    requests = [event for event in parent_events if event["type"] == "evolution_requested"]
    if not requests:
        return _result("unverifiable", "lifecycle_request_missing")
    if len(requests) != 1:
        return _result("failed", "lifecycle_request_count")
    request = requests[0]["payload"]
    if (type(request.get("automatic_lifecycle_version")) is not int
            or request["automatic_lifecycle_version"] != 1 or request.get("bundle_mode") != "compiled"
            or type(request.get("solve_wall_timeout")) not in {int, float}
            or request["solve_wall_timeout"] != 3000
            or request.get("solve_wall_timeout_source") != "explicit"):
        return _result("failed", "lifecycle_policy_mismatch")

    with store._connect() as connection:
        tasks = connection.execute(
            "SELECT id,run_id,orchestration,state,attempts FROM tasks "
            "WHERE (run_id = ? AND orchestration != 0) OR id = ? LIMIT 3",
            (parent_id, task_id),
        ).fetchall()
        attempts = connection.execute(
            "SELECT id,task_id,runtime,status FROM attempts WHERE task_id = ? LIMIT 2", (task_id,),
        ).fetchall()
    if not tasks:
        return _result("unverifiable", "lifecycle_orchestration_missing")
    if (len(tasks) != 1 or tasks[0]["id"] != task_id or tasks[0]["run_id"] != parent_id
            or tasks[0]["orchestration"] != 1):
        return _result("failed", "lifecycle_orchestration_mismatch")
    if not attempts:
        return _result("unverifiable", "lifecycle_attempt_missing")
    if len(attempts) != 1 or tasks[0]["attempts"] != 1:
        return _result("failed", "lifecycle_attempt_count")
    attempt = attempts[0]
    if attempt["runtime"] != "automatic-solve":
        return _result("failed", "lifecycle_attempt_owner")
    claims = [event for event in parent_events
              if event["type"] == "task_claimed" and event["task_id"] == task_id]
    started = [event for event in parent_events
               if event["type"] == "automatic_solve_orchestration_started"]
    if not claims or not started:
        return _result("unverifiable", "lifecycle_attempt_receipt_missing")
    if (len(claims) != 1 or len(started) != 1
            or claims[0]["payload"].get("attempt_id") != attempt["id"]
            or claims[0]["payload"].get("runtime") != "automatic-solve"
            or type(claims[0]["payload"].get("attempt")) is not int
            or claims[0]["payload"]["attempt"] != 1
            or started[0]["payload"] != {"task_id": task_id, "attempt_id": attempt["id"]}
            or started[0]["task_id"] is not None
            or claims[0]["sequence"] >= started[0]["sequence"]):
        return _result("failed", "lifecycle_attempt_receipt_mismatch")

    executions = [event for event in parent_events if event["type"] == "solve_execution"]
    if not executions:
        return _result("unverifiable", "lifecycle_execution_missing")
    fields = {"schema_version", "execution_id", "scope", "policy_seconds", "policy_origin",
              "stage", "state", "stopping_reason"}
    for event in executions:
        item = event["payload"]
        if (set(item) != fields or item.get("schema_version") != "1"
                or item.get("execution_id") != execution_id
                or re.fullmatch(r"solve-[0-9a-f]{32}", execution_id) is None
                or item.get("scope") != "active_execution"
                or type(item.get("policy_seconds")) not in {int, float}
                or item["policy_seconds"] != 3000 or item.get("policy_origin") != "explicit"
                or type(item.get("stage")) is not str or item["stage"] not in _STAGES
                or type(item.get("state")) is not str or item["state"] not in _STATES
                or item.get("stopping_reason") not in _REASONS or event["task_id"] is not None):
            return _result("failed", "lifecycle_execution_mismatch")

    # Full history wins over the latest diagnostic or rewritten current status.
    for event in events:
        failure = event["type"] in _FAILURES
        failure |= (event["run_id"] == parent_id and event["task_id"] == task_id
                    and event["type"] in {"task_cancelled", "task_failed", "task_recovered"})
        failure |= (event["type"] == "solve_execution"
                    and event["payload"].get("stopping_reason") in {
                        "cancelled", "solve_wall_timeout", "failed", "interrupted",
                    })
        if failure:
            return _result("failed", "lifecycle_terminal_failure")

    delivery = [event for event in parent_events if event["type"] == "bundle_candidate_delivered"]
    task_success = [event for event in parent_events
                    if event["type"] == "task_succeeded" and event["task_id"] == task_id]
    parent_success = [event for event in parent_events if event["type"] == "run_succeeded"]
    child_success = [event for event in child_events if event["type"] == "run_succeeded"]
    if not delivery or not task_success or not parent_success or not child_success:
        return _result("unverifiable", "lifecycle_completion_missing")
    if any(len(items) != 1 for items in (delivery, task_success, parent_success, child_success)):
        return _result("failed", "lifecycle_completion_count")
    payload = delivery[0]["payload"]
    if (payload.get("schema_version") != "1" or payload.get("mode") != "bundle"
            or payload.get("status") != "succeeded" or payload.get("parent_run_id") != parent_id
            or payload.get("evolution_run_id") != child_id
            or payload.get("contract_sha256") != contract_digest
            or not isinstance(payload.get("validation"), dict)
            or payload["validation"].get("passed") is not True
            or payload.get("error") is not None
            or delivery[0]["task_id"] is not None
            or parent_success[0]["task_id"] is not None
            or child_success[0]["task_id"] is not None
            or task_success[0]["payload"].get("attempt_id") != attempt["id"]
            or parent.status.value != "succeeded" or child.status.value != "succeeded"
            or tasks[0]["state"] != "succeeded" or attempt["status"] != "succeeded"):
        return _result("failed", "lifecycle_completion_mismatch")
    if not (started[0]["sequence"] < child_success[0]["sequence"] < delivery[0]["sequence"]
            < task_success[0]["sequence"] < parent_success[0]["sequence"]):
        return _result("failed", "lifecycle_completion_order")
    terminal = [event for event in executions if event["payload"]["state"] == "terminal"]
    if not terminal:
        return _result("unverifiable", "lifecycle_terminal_missing")
    if (len(terminal) != 1 or terminal[0] != executions[-1]
            or terminal[0]["payload"]["stopping_reason"] != "completed"
            or terminal[0]["sequence"] < parent_success[0]["sequence"]):
        return _result("failed", "lifecycle_terminal_mismatch")
    return _result("verified")
