"""Durable observations of native boundaries; never substitute a model or evaluator.

All timestamps use the request guard's monotonic clock. The trace records actual
Store admissions and execution/evaluation returns, including the explicit bridge
from an AgentRequest's temporary identity to the controller-owned Store identity.
"""
from __future__ import annotations

import hashlib
import math
import os
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from famou import bundle_evolution
from famou.candidate_evaluation_spec import canonical_json
from famou.candidate_generation_receipt import build_candidate_generation_receipt
from famou.store import Store


@contextmanager
def traced_native(guard):
    path = guard.journal_path.parent / "native-trace.jsonl"
    digest = hashlib.sha256()
    count = 0
    origin = guard.clock() - guard.started
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)

        def clock():
            value = guard.clock() - guard.started
            if not math.isfinite(value) or value < 0:
                raise ValueError("native_trace_clock_invalid")
            return value

        def append(stage, started, binding, outcome="succeeded"):
            nonlocal count
            row = {"schema_version": "1", "index": count + 1, "stage": stage,
                   "outcome": outcome, "started_at": started, "finished_at": clock(),
                   "binding": binding, "previous_sha256": digest.hexdigest()}
            raw = canonical_json(row) + b"\n"
            stream.write(raw.decode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
            digest.update(raw)
            count += 1
            guard.native_trace = {"rows": count, "sha256": digest.hexdigest()}

        native_event = Store.append_event
        native_generation = Store.append_candidate_generation_event
        native_execution = bundle_evolution.run_candidate_execution_recorded
        native_evaluation = bundle_evolution.evaluate_candidate_execution

        def event(store, run_id, event_type, payload, task_id=None, event_id=None):
            started = clock()
            result = native_event(store, run_id, event_type, payload, task_id, event_id)
            stages = {"bundle_profile_prepared": "preparation",
                      "evolution_finished": "selection",
                      "bundle_candidate_delivered": "parent_delivery"}
            if result is True and event_type in stages:
                append(stages[event_type], origin if event_type == "bundle_profile_prepared" else started,
                       {"run_id": run_id, "task_id": task_id,
                        "event_type": event_type,
                        "payload_sha256": hashlib.sha256(canonical_json(payload)).hexdigest()})
            return result

        def generation(store, run_id, task_id, payload):
            result = native_generation(store, run_id, task_id, payload)
            if result is not True:
                raise ValueError("native_generation_replayed")
            receipt = build_candidate_generation_receipt(payload, run_id=run_id, task_id=task_id)
            context = guard.native_requests.get(receipt["budget_id"])
            if context is None:
                raise ValueError("native_generation_request_missing")
            append("candidate_generation", context["started_at"], {
                "run_id": run_id, "task_id": task_id, "budget_id": receipt["budget_id"],
                "wire_run_id": context["run_id"], "wire_task_id": context["task_id"],
                "max_tool_steps": context["max_tool_steps"],
                "candidate_id": receipt.get("candidate_id"),
                "bundle_sha256": receipt.get("source_bundle_sha256"),
                "payload_sha256": hashlib.sha256(canonical_json(receipt)).hexdigest(),
            }, "succeeded" if receipt["completion"] else "failed")
            return result

        def execution(admission, *, plan, **kwargs):
            started = clock()
            result = native_execution(admission, plan=plan, **kwargs)
            append("candidate_execution", started, {
                "admission_sha256": admission.digest(), "plan_sha256": plan.digest(),
                "completion_sha256": result.completion_sha256,
            }, "succeeded" if result.to_dict().get("runner_result", {}).get("status") == "succeeded" else "failed")
            return result

        def evaluation(admission, *, plan, **kwargs):
            started = clock()
            result = native_evaluation(admission, plan=plan, **kwargs)
            append("independent_scoring", started, {
                "admission_sha256": admission.digest(), "plan_sha256": plan.digest(),
                "evaluation_sha256": result.digest(),
            })
            return result

        guard.native_trace = {"rows": count, "sha256": digest.hexdigest()}
        with ExitStack() as stack:
            for owner, name, replacement in (
                (Store, "append_event", event),
                (Store, "append_candidate_generation_event", generation),
                (bundle_evolution, "run_candidate_execution_recorded", execution),
                (bundle_evolution, "evaluate_candidate_execution", evaluation),
            ):
                stack.enter_context(patch.object(owner, name, replacement))
            try:
                yield
            finally:
                with path.with_name("native-trace-closed.json").open("x", encoding="utf-8") as terminal:
                    os.chmod(terminal.name, 0o600)
                    terminal.write(canonical_json(guard.native_trace).decode("utf-8") + "\n")
                    terminal.flush()
                    os.fsync(terminal.fileno())
