"""Read-only semantic audit of retained automatic-solve evidence.

This is an observation API, not a launcher or preregistration. Native records are
inspected at their original paths; only SQLite is copied to a private snapshot.
Legacy execution records have no independent cleanup observation and therefore cannot establish
primary eligibility. New records may carry the separate cleanup-v1 receipt; this auditor accepts
that boundary only after its descriptor, identities, probe, and exit bindings verify.
"""
from __future__ import annotations

import hashlib
import sqlite3

from ._audit_lifecycle import audit_parent_lifecycle
from ._audit_request import (
    AcceptanceAuditError,
    build_acceptance_audit_request,
    parse_acceptance_audit_request,
)
from ._audit_slots import audit_execution_slots
from ._audit_snapshot import AuditSnapshotError, audit_events, audit_snapshot
from ._benchmark_files import absolute_path, read_regular_file
from ._candidate_workspace_io import DirectoryChain
from .acceptance_observer import AcceptanceObservationError, observe_acceptance_evidence
from .automatic_solve_bundle import validate_automatic_solve_bundle
from .bundle_evolution import load_bundle_pipeline
from .bundle_parent_delivery import inspect_bundle_parent_delivery
from .campaign_inventory import audit_campaign_directory, inventory_campaign_directory
from .candidate_evaluation import inspect_candidate_evaluation
from .candidate_evaluation_spec import candidate_output_contract_sha256, canonical_json
from .candidate_execution import MAX_EXECUTION_ADMISSION_BYTES, parse_candidate_execution_admission
from .candidate_execution_evidence import inspect_candidate_execution_record
from .candidate_generation_receipt import inspect_candidate_generation_events
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .controller import LocalController
from .evolution import EvolutionError
from .holdout_audit import audit_holdout_receipts

_BOUNDARIES = (
    "receipt_chain", "snapshot", "preparation", "generation", "slot_identity", "execution",
    "scoring", "selection", "delivery", "lifecycle",
)
_EXPECTED_FAILURES = (OSError, ValueError, TypeError, KeyError, AttributeError,
                      RecursionError, sqlite3.Error, EvolutionError)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _BoundaryProblem(Exception):
    def __init__(self, status: str, reason: str):
        self.status, self.reason = status, reason


def _require(condition, reason, *, status="failed"):
    if not condition:
        raise _BoundaryProblem(status, reason)


def _boundary(name, status="verified", reason=None, digests=None):
    return {"boundary": name, "status": status, "reason": reason,
            "verified_digests": digests or {}}


class _NativeAudit:
    def __init__(self, request, store, root, receipts):
        self.request, self.store, self.root, self.receipts = request, store, root, receipts
        self.ids, self.pins = request["identities"], request["pins"]
        self.manifest = request["manifest"]
        self.paths = request["paths"]
        self.parent = self.child = self.contract = self.record = self.plan = self.admission = None
        self.pipeline = self.evaluation = self.selected_identity = None
        # Never call LocalController.__init__: it initializes Store, memory and workers.
        # These native inspection methods only need a read-only Store; no runtime exists.
        self.controller = object.__new__(LocalController)
        self.controller.store = store
        self.events = []

    def capture(self, name):
        try:
            digests = getattr(self, name)()
            return _boundary(name, digests=digests)
        except _BoundaryProblem as exc:
            return _boundary(name, exc.status, exc.reason)
        except _EXPECTED_FAILURES:
            return _boundary(name, "unverifiable", name + "_evidence_unverifiable")

    def snapshot(self):
        self.parent = self.store.get_run(self.ids["parent_run_id"])
        self.child = self.store.get_run(self.ids["child_run_id"])
        _require(self.parent is not None and self.child is not None,
                 "run_missing", status="unverifiable")
        for name, run in (("parent_workspace", self.parent), ("child_workspace", self.child)):
            expected = self.root / self.paths[name]
            _require(absolute_path(run.workspace) == expected, "workspace_identity_mismatch",
                     status="unverifiable")
            held = DirectoryChain(expected, "workspace_unsafe")
            held.close()
        _require(self.child.workspace == self.parent.workspace / "evolution-run",
                 "child_workspace_mismatch")
        self.events = audit_events(self.store, self.parent.id, self.child.id)
        self.contract = self.controller._algorithm_contract(self.parent)
        _require(self.contract is not None, "contract_missing", status="unverifiable")
        _require(self.contract.digest() == self.pins["contract_sha256"], "contract_mismatch")
        return {"contract_sha256": self.contract.digest()}

    def preparation(self):
        _require(self.contract is not None, "contract_unverified", status="unverifiable")
        prepared = [event for event in self.events if event["run_id"] == self.parent.id
                    and event["type"] == "bundle_profile_prepared"]
        _require(bool(prepared), "prepared_receipt_missing", status="unverifiable")
        _require(len(prepared) == 1, "prepared_receipt_count")
        policies = [event["payload"] for event in self.events
                    if event["run_id"] == self.parent.id and event["type"] == "evolution_requested"]
        _require(len(policies) == 1, "preparation_policy_missing", status="unverifiable")
        policy = policies[0]
        _require(policy.get("automatic_lifecycle_version") == 1
                 and policy.get("bundle_mode") == "compiled"
                 and policy.get("solve_wall_timeout") == 3000
                 and policy.get("solve_wall_timeout_source") == "explicit",
                 "preparation_policy_mismatch")
        budget_keys = {
            "timeout": "request_timeout_seconds",
            "evaluator_preparation_timeout": "preparation_request_timeout_seconds",
            "evaluator_preparation_wall_timeout": "preparation_wall_seconds",
        }
        for key, declared_key in budget_keys.items():
            _require(key in policy, "preparation_budget_missing", status="unverifiable")
            _require(type(policy[key]) in {int, float}
                     and policy[key] == self.manifest["budgets"][declared_key],
                     "preparation_budget_mismatch")
        if "candidate_generation_max_steps" in policy:
            _require(policy["candidate_generation_max_steps"] == 12,
                     "preparation_policy_mismatch")
        validate_automatic_solve_bundle(self.store, self.parent.id)
        _require(prepared[0]["payload"].get("profile_sha256") == self.pins["profile_sha256"],
                 "profile_digest_mismatch")
        pipeline = load_bundle_pipeline(self.parent.workspace / "bundle-profile.json")
        _require(pipeline.evaluator.harness_sha256 == self.manifest["evaluator_sha256"],
                 "evaluator_digest_mismatch")
        inputs_digest = _sha(canonical_json([item.to_dict() for item in pipeline.inputs]))
        _require(inputs_digest == self.manifest["input_sha256"], "input_digest_mismatch")
        self.pipeline = pipeline
        return {"profile_sha256": self.pins["profile_sha256"], "input_sha256": inputs_digest,
                "evaluator_sha256": self.manifest["evaluator_sha256"]}

    def generation(self):
        task = self.store.get_task(self.ids["generation_task_id"])
        _require(task is not None, "generation_task_missing", status="unverifiable")
        _require(task.run_id == self.ids["child_run_id"] and not task.orchestration,
                 "generation_task_mismatch")
        events = [event for event in self.events if event["type"] == "agent_candidate_generation"]
        _require(bool(events), "generation_receipt_missing", status="unverifiable")
        _require(len(events) == 1, "generation_slot_count")
        event = events[0]
        _require(event["run_id"] == self.ids["child_run_id"]
                 and event["task_id"] == self.ids["generation_task_id"], "generation_owner_mismatch")
        summary = inspect_candidate_generation_events(
            events, run_id=self.ids["child_run_id"], task_id=self.ids["generation_task_id"],
        )
        payload = event["payload"]
        _require(summary == {"receipt_count": 1, "completed": 1},
                 "generation_not_completed", status=(
                     "failed" if payload["outcome"] == "failed" else "unverifiable"))
        observed = observe_acceptance_evidence(
            self.manifest, self.receipts, generation_events=events,
            generation_run_id=self.ids["child_run_id"],
            generation_task_id=self.ids["generation_task_id"],
        )
        _require(observed["generation_receipt"] == {"receipt_count": 1, "completed": 1},
                 "generation_not_completed", status=(
                     "failed" if payload["outcome"] == "failed" else "unverifiable"))
        _require(payload["candidate_id"] == self.ids["candidate_id"]
                 and payload["budget_id"] == self.ids["generation_budget_id"]
                 and payload["source_bundle_sha256"] == self.pins["bundle_sha256"],
                 "generation_identity_mismatch")
        return {"bundle_sha256": self.pins["bundle_sha256"]}

    def execution(self):
        _require(self.child is not None, "child_missing", status="unverifiable")
        plan = parse_candidate_workspace_plan(self.child.workspace / self.paths["plan"])
        admission = parse_candidate_execution_admission(read_regular_file(
            self.child.workspace / self.paths["admission"], MAX_EXECUTION_ADMISSION_BYTES,
        ))
        record = inspect_candidate_execution_record(
            self.child.workspace / self.paths["execution"], plan=plan, admission=admission,
            expected_plan_sha256=self.pins["plan_sha256"],
            expected_admission_sha256=self.pins["admission_sha256"],
            expected_bundle_sha256=self.pins["bundle_sha256"],
            expected_contract_sha256=self.pins["contract_sha256"],
            expected_completion_sha256=self.pins["completion_sha256"],
        )
        _require(record.status == "recorded", "execution_uncertain", status="unverifiable")
        runner = record.to_dict()["runner_result"]
        _require(runner["status"] == "succeeded" and runner["execution"]["status"] == "succeeded"
                 and runner["execution"]["exit_code"] == 0, "execution_failed")
        # Retain verified native pins for independent scoring checks. Cleanup is a separate
        # supervisor receipt; a missing legacy receipt remains unknown and cannot be inferred
        # from the process exit code.
        self.plan, self.admission, self.record = plan, admission, record
        if record.cleanup_status == "failed":
            raise _BoundaryProblem("failed", "execution_cleanup_failed")
        if record.cleanup_status != "verified":
            raise _BoundaryProblem("unverifiable", "execution_cleanup_unknown")
        return {"completion_sha256": record.completion_sha256,
                "cleanup_sha256": record.cleanup_sha256}

    def slot_identity(self):
        _require(self.child is not None, "child_missing", status="unverifiable")
        result = audit_execution_slots(
            self.child.workspace, **{key + "_path": self.paths[key]
                                     for key in ("plan", "admission", "execution", "evaluation")},
        )
        _require(result["status"] == "verified", result["reason"], status=result["status"])
        return {}

    def scoring(self):
        _require(self.record is not None and self.pipeline is not None,
                 "scoring_dependency_unverified", status="unverifiable")
        result = inspect_candidate_evaluation(
            self.child.workspace / self.paths["evaluation"],
            expected_evaluation_sha256=self.pins["evaluation_sha256"],
        )
        expected = {
            "workspace_plan_sha256": self.pins["plan_sha256"],
            "admission_sha256": self.pins["admission_sha256"],
            "bundle_sha256": self.pins["bundle_sha256"],
            "contract_sha256": self.pins["contract_sha256"],
            "evaluator_fingerprint": self.pipeline.evaluator.digest(),
            "launch_intent_sha256": self.record.launch_intent_sha256,
            "completion_sha256": self.pins["completion_sha256"],
            "source_file_table_sha256": self.plan.file_table_sha256,
            "input_file_table_sha256": self.manifest["input_sha256"],
            "output_contract_sha256": candidate_output_contract_sha256(self.contract.outputs),
        }
        value = result.to_dict()
        _require(value["binding"] == expected, "evaluation_binding_mismatch")
        _require(self.admission.evaluator == self.pipeline.evaluator.pin()
                 and self.admission.output_contract_sha256 == expected["output_contract_sha256"]
                 and _sha(canonical_json([i.to_dict() for i in self.admission.inputs]))
                 == expected["input_file_table_sha256"], "evaluation_admission_mismatch")
        _require(result.report.validity == 1 and value["output_contract_valid"] is True
                 and value["harness_invoked"] is True, "evaluation_invalid")
        self.evaluation = result
        return {"evaluation_sha256": result.digest()}

    def selection(self):
        _require(self.evaluation is not None, "selection_dependency_unverified", status="unverifiable")
        identity, _materials, _result = self.controller._verified_bundle_evolution_delivery(self.child.id)
        _require(identity == {
            "candidate_id": self.ids["candidate_id"], "contract_sha256": self.pins["contract_sha256"],
            "bundle_sha256": self.pins["bundle_sha256"], "receipt_sha256": self.pins["selection_sha256"],
            "evaluation_sha256": self.pins["evaluation_sha256"],
        }, "selection_identity_mismatch")
        archived = [event for event in self.events if event["type"] == "evolution_candidate_archived"]
        _require(len(archived) == 1 and archived[0]["run_id"] == self.child.id
                 and archived[0]["task_id"] == self.ids["generation_task_id"]
                 and archived[0]["payload"].get("candidate_id") == self.ids["candidate_id"],
                 "selection_slot_mismatch")
        self.selected_identity = identity
        return {"selection_sha256": identity["receipt_sha256"]}

    def delivery(self):
        _require(self.selected_identity is not None, "delivery_dependency_unverified", status="unverifiable")
        result = inspect_bundle_parent_delivery(
            self.controller, self.parent.id, self.child.id, self.contract,
        )
        _require(result.get("status") == "succeeded" and result["validation"]["passed"] is True,
                 "delivery_failed")
        _require(result["delivery_sha256"] == self.pins["delivery_sha256"], "delivery_digest_mismatch")
        return {"delivery_sha256": result["delivery_sha256"]}


def audit_acceptance_artifacts(
    request, *, database, audit_root, stage_receipts, holdout_receipts=(), retained_snapshots=None,
):
    """Audit retained evidence without execution, repair, or acceptance-counter changes.

    ``audit_root`` confines the declared original workspaces. ``database`` is copied
    separately and never opened by SQLite in place. Inputs/expected/actual holdout
    bytes are supplied to ``retained_snapshots`` as in :func:`audit_holdout_receipts`.
    No caller-supplied primary eligibility flag is accepted by this combined API.
    """
    parsed = parse_acceptance_audit_request(request)
    try:
        observation = observe_acceptance_evidence(parsed["manifest"], stage_receipts)
    except AcceptanceObservationError:
        raise AcceptanceAuditError("audit_stage_receipts_invalid") from None
    stages = {item["stage"]: item for item in stage_receipts}
    pin_names = {"preparation": "profile_sha256", "generation": "bundle_sha256",
                 "execution": "completion_sha256", "scoring": "evaluation_sha256",
                 "selection": "selection_sha256", "delivery": "delivery_sha256"}
    if any(item["artifact_sha256"] is not None
           and item["artifact_sha256"] != parsed["pins"][pin_names[name]]
           for name, item in stages.items()):
        raise AcceptanceAuditError("audit_stage_digest_mismatch")
    boundaries = {name: _boundary(name, "unverifiable", "not_observed") for name in _BOUNDARIES}
    boundaries["receipt_chain"] = _boundary(
        "receipt_chain", "verified" if observation["chain_complete"] else (
            "failed" if observation["status"] == "failed" else "unverifiable"),
        None if observation["chain_complete"] else "stage_receipts_incomplete",
    )
    try:
        root = absolute_path(audit_root)
        _require(root.name == parsed["manifest"]["campaign_root"], "campaign_root_mismatch")
        held = DirectoryChain(root, "campaign_root_unsafe")
        try:
            with audit_snapshot(database) as store:
                audit = _NativeAudit(parsed, store, root, stage_receipts)
                boundaries["snapshot"] = audit.capture("snapshot")
                if boundaries["snapshot"]["status"] == "verified":
                    before = inventory_campaign_directory(audit.parent.workspace)
                    for name in ("preparation", "generation", "slot_identity", "execution",
                                 "scoring", "selection", "delivery"):
                        boundaries[name] = audit.capture(name)
                    life = audit_parent_lifecycle(
                        store, parent_id=audit.ids["parent_run_id"], child_id=audit.ids["child_run_id"],
                        orchestration_task_id=audit.ids["orchestration_task_id"],
                        solve_execution_id=audit.ids["solve_execution_id"],
                        contract_sha256=audit.pins["contract_sha256"],
                    )
                    boundaries["lifecycle"] = _boundary("lifecycle", life["status"], life["reason"])
                    audit_campaign_directory(audit.parent.workspace, before)
                held.check()
        finally:
            held.close()
    except _BoundaryProblem as exc:
        boundaries["snapshot"] = _boundary("snapshot", exc.status, exc.reason)
    except AuditSnapshotError:
        boundaries["snapshot"] = _boundary("snapshot", "unverifiable", "store_snapshot_unverifiable")
    except _EXPECTED_FAILURES:
        boundaries["snapshot"] = _boundary("snapshot", "unverifiable", "workspace_snapshot_unverifiable")

    primary = all(item["status"] == "verified" for item in boundaries.values())
    holdouts = audit_holdout_receipts(
        parsed["holdout_declaration"], holdout_receipts,
        retained_snapshots=retained_snapshots, primary_eligible=primary,
    )
    first = next((item for item in boundaries.values() if item["status"] != "verified"), None)
    if first is None and holdouts["first_problem"] is not None:
        first = {"boundary": "holdouts", **holdouts["first_problem"]}
    return {
        "schema_version": "1", "scope": "acceptance_semantic_audit",
        "audit_request_sha256": parsed["audit_request_sha256"],
        "manifest_sha256": parsed["manifest"]["manifest_sha256"],
        **{key: parsed["manifest"][key] for key in ("registration_id", "campaign_id", "attempt_id")},
        "boundaries": list(boundaries.values()), "first_problem": first,
        "holdout_counts": holdouts["holdout_counts"], "holdouts": holdouts["holdouts"],
        "primary_eligible": primary, "joint_eligible": holdouts["joint_eligible"],
        "preparation_success": "0/1", "primary_success": "0/1", "joint_success": "0/1",
        "provider_called_during_audit": False, "executed_during_audit": False,
        "mutated_during_audit": False, "real_acceptance_claimed": False,
    }


__all__ = [
    "AcceptanceAuditError", "audit_acceptance_artifacts", "build_acceptance_audit_request",
    "parse_acceptance_audit_request",
]
