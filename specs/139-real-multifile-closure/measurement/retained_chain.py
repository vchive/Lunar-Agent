"""Verify native, retained six-stage evidence without executing retained code."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from famou._benchmark_files import read_regular_file
from famou.bundle_delivery import inspect_bundle_delivery
from famou.bundle_evolution import read_bundle_delivery_materials
from famou.candidate_evaluation_spec import canonical_json, strict_json
from famou.controller import LocalController
from famou.evolution import (
    MAX_ARCHIVE_LINE_BYTES,
    MAX_STATE_BYTES,
    ORDINARY_RECEIPT_FILENAME,
    ORDINARY_RECORD_FILENAME,
    Candidate,
    CandidateArchive,
    EvolutionConfig,
    EvolutionContext,
    PopulationStrategy,
    StrategyResult,
    resolve_candidate_integrity_authority,
)

from .campaign import STAGE_ORDER, default_manifest
from .native_receipts import candidate_generation_receipt


class _ReadOnlyController(LocalController):
    def __init__(self, store):
        # The native read-only inspection methods need only a Store. Avoid the
        # ordinary constructor, which initializes databases and runtime state.
        self.store = store


class _ReadOnlyArchive(CandidateArchive):
    def __init__(self, workspace):
        # The product constructor can recover a seed publication. Never call it
        # during an audit, even if the ordinary happy path would write nothing.
        self.workspace = Path(workspace)
        self.root = self.workspace / "evolution"
        self.candidates_root = self.root / "candidates"
        self.archive_path = self.root / "archive.jsonl"
        self.offspring_outcomes_path = self.root / "offspring-outcomes.jsonl"
        self.state_path = self.root / "state.json"
        self.seed_commit_path = self.root / "seed-commit.json"
        for path in (self.workspace, self.root, self.candidates_root):
            if path.is_symlink() or not path.is_dir():
                raise ValueError("native_archive_missing")
        if any(path.name.startswith(".evolution-seed-") for path in self.workspace.iterdir()):
            raise ValueError("native_seed_recovery_forbidden")


def _inactive(*_args, **_kwargs):
    raise ValueError("native_audit_execution_forbidden")


def _verified_selection(reader, child, contract):
    """Reuse native read validators without writer/recovery constructors."""
    workspace = Path(child.workspace)
    extra = {"evolution/contract.json": ("evolution_contract", MAX_STATE_BYTES)}
    snapshots = reader._materialization_artifact_snapshots(child, workspace, additional=extra)
    if strict_json(snapshots["evolution/contract.json"]) != contract.to_dict():
        raise ValueError("native_contract_mismatch")
    state = strict_json(snapshots["evolution/state.json"])
    payload = strict_json(snapshots["evolution/result.json"])
    result = StrategyResult(**payload)
    if (result.strategy != "population" or result.status not in {"completed", "stagnated"}
            or state.get("status") != result.status or state.get("iteration") != result.iterations):
        raise ValueError("native_selection_invalid")
    configuration = dict(state["config"])
    if configuration.pop("command_sha256", None) is not None:
        raise ValueError("native_configuration_invalid")
    config = EvolutionConfig(**configuration)
    context = EvolutionContext(contract=contract, workspace=workspace, generate=_inactive,
                               evaluate=_inactive, config=config)
    strategy = PopulationStrategy.__new__(PopulationStrategy)
    strategy.context, strategy.config = context, config
    strategy.archive = _ReadOnlyArchive(workspace)
    strategy.integrity_authority = resolve_candidate_integrity_authority(context)
    strategy.validate_ordinary_resume_integrity()
    archive = strategy.archive
    canonical = archive.result(result.strategy, result.status, result.iterations, result.error)
    if canonical.to_dict() != payload:
        raise ValueError("native_selection_invalid")
    reader._validate_materialization_child_events(child, contract, result)
    selected = archive.best()
    if selected is None or selected.bundle_evidence is None:
        raise ValueError("native_selection_invalid")
    for candidate in archive.records():
        for filename, kind in ((ORDINARY_RECORD_FILENAME, "evolution_candidate_record"),
                               (ORDINARY_RECEIPT_FILENAME, "evolution_candidate_receipt")):
            extra[(Path(candidate.code_path).parent / filename).as_posix()] = (kind, MAX_ARCHIVE_LINE_BYTES)
    bound = reader._materialization_artifact_snapshots(child, workspace, additional=extra)
    if any(bound[name] != content for name, content in snapshots.items()):
        raise ValueError("native_selection_changed")
    materials = read_bundle_delivery_materials(workspace, selected, authority=strategy.integrity_authority)
    if bound != reader._materialization_artifact_snapshots(child, workspace, additional=extra):
        raise ValueError("native_selection_changed")
    return {"candidate_id": selected.candidate_id, "contract_sha256": contract.digest(),
            "bundle_sha256": selected.bundle_evidence["bundle_sha256"],
            "receipt_sha256": selected.receipt_sha256,
            "evaluation_sha256": selected.bundle_evidence["evaluation_sha256"]}, materials, canonical


def _sha(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _read(path, maximum=4 * 1024 * 1024):
    return strict_json(read_regular_file(path, maximum), maximum=maximum)


def _trace(slot):
    content = read_regular_file(slot / "native-trace.jsonl", 4 * 1024 * 1024)
    digest = hashlib.sha256()
    rows = []
    previous_end = 0.0
    for line in content.splitlines(keepends=True):
        row = strict_json(line, maximum=128 * 1024)
        if (type(row) is not dict or set(row) != {
                "schema_version", "index", "stage", "outcome", "started_at", "finished_at",
                "binding", "previous_sha256",
        } or row["schema_version"] != "1" or type(row["index"]) is not int
                or row["index"] != len(rows) + 1 or row["stage"] not in STAGE_ORDER
                or row["outcome"] != "succeeded" or type(row["binding"]) is not dict
                or row["previous_sha256"] != digest.hexdigest()):
            raise ValueError("native_trace_invalid")
        start, finish = row["started_at"], row["finished_at"]
        if (any(type(value) not in (float, int) or not math.isfinite(value) for value in (start, finish))
                or not previous_end <= start <= finish < default_manifest()["budgets"]["wall_seconds"]):
            raise ValueError("native_trace_time_invalid")
        previous_end = finish
        rows.append(row)
        digest.update(line)
    anchor = {"rows": len(rows), "sha256": digest.hexdigest()}
    if _read(slot / "native-trace-closed.json") != anchor:
        raise ValueError("native_trace_closure_mismatch")
    worker_path = slot / "worker-finished.json"
    if worker_path.exists():
        worker = _read(worker_path)
        guard = worker.get("guard", {})
        elapsed = guard.get("elapsed_seconds")
        if (guard.get("native_trace") != anchor or type(elapsed) not in (float, int)
                or not math.isfinite(elapsed) or previous_end > elapsed
                or elapsed > worker.get("elapsed_seconds", -1)):
            raise ValueError("native_trace_worker_mismatch")
    return rows, anchor


def _event(events, kind, row, run_id):
    matches = [event for event in events if event.get("type") == kind]
    if len(matches) != 1:
        raise ValueError("native_stage_event_missing")
    event = matches[0]
    expected = {"run_id": run_id, "task_id": event["task_id"], "event_type": kind,
                "payload_sha256": _sha(event["payload"])}
    if row["binding"] != expected:
        raise ValueError("native_stage_event_mismatch")
    return event["payload"]


def verify_retained_chain(slot, store, parent, contract, cli):
    """Bind native parser completion, execution, score, selection and delivery.

The product's original read-only delivery inspector revalidates archive ranking,
Store artifacts, inode-bound execution records and exact evaluation snapshots.
This measurement additionally requires parser-complete Store receipts and every
actual provider turn, with no inference from delivery back to generation.
    """
    from .analysis import transport_summary, usage_summary

    slot = Path(slot)
    rows, anchor = _trace(slot)
    terminal = cli["evolution"]["materialization"]
    child_id = terminal["evolution_run_id"]
    child = store.get_run(child_id)
    if child is None or Path(child.workspace) != slot / "workspace/evolution-run":
        raise ValueError("native_child_missing")
    reader = _ReadOnlyController(store)
    identity, materials, result = _verified_selection(reader, child, contract)
    if any(terminal.get(key) != value for key, value in identity.items()):
        raise ValueError("native_selection_delivery_mismatch")
    workspace = slot / "workspace"
    package = inspect_bundle_delivery(
        workspace / terminal["delivery_path"], expected_delivery_sha256=terminal["delivery_sha256"],
    )
    if package.to_dict()["identity"] != identity:
        raise ValueError("native_delivery_identity_mismatch")
    # Comparing every retained portable byte also binds the exact evaluated
    # input/output/report and source to what the parent actually published.
    for name, raw in materials.items():
        if read_regular_file(package.delivery_path / name, max(1, len(raw))) != raw:
            raise ValueError("native_delivery_material_mismatch")

    snapshots = reader._materialization_artifact_snapshots(child, Path(child.workspace))
    candidates = [Candidate.from_dict(strict_json(line))
                  for line in snapshots["evolution/archive.jsonl"].splitlines() if line.strip()]
    count = len(candidates)
    population = default_manifest()["population"]
    maximum = population["members"] + population["offspring_per_round"] * population["rounds"]
    if not 1 <= count <= maximum or len({item.candidate_id for item in candidates}) != count:
        raise ValueError("native_candidate_count_invalid")
    expected_stages = ["preparation"] + [
        stage for _ in candidates for stage in ("candidate_generation", "candidate_execution", "independent_scoring")
    ] + ["selection", "parent_delivery"]
    if [row["stage"] for row in rows] != expected_stages:
        raise ValueError("native_stage_chain_incomplete")
    tasks = store.list_tasks(child_id)
    if len(tasks) != 1:
        raise ValueError("native_task_missing")
    task_id = tasks[0].id
    parent_events, child_events = store.list_events(parent.id), store.list_events(child_id)
    preparation = _event(parent_events, "bundle_profile_prepared", rows[0], parent.id)
    selection = _event(child_events, "evolution_finished", rows[-2], child_id)
    delivery = _event(parent_events, "bundle_candidate_delivered", rows[-1], parent.id)
    if (selection != result.to_dict() or delivery != terminal
            or identity["contract_sha256"] != contract.digest()
            or rows[0]["finished_at"] >= default_manifest()["budgets"]["preparation_wall_seconds"]):
        raise ValueError("native_stage_binding_invalid")

    usage = usage_summary(slot / "calls.jsonl")
    transport_summary(slot / "transport.jsonl", usage["requests"])
    requests = usage["requests"]
    if (usage["pending_requests"] or any(row["outcome"] != "succeeded" for row in requests)
            or [row["stage"] for row in requests[:3]] != [
                "contract_compiler", "evaluator_compiler", "evaluator_auditor",
            ] or any(row["stage"] != "candidate_generation" for row in requests[3:])):
        raise ValueError("native_requests_incomplete")
    for request in requests[:3]:
        start = request.get("started_elapsed_seconds")
        if (start is None or not rows[0]["started_at"] <= start
                <= start + request["elapsed_seconds"] <= rows[0]["finished_at"]):
            raise ValueError("native_preparation_request_time_mismatch")
    expected_receipts = [event for event in child_events if event.get("type") == "agent_candidate_generation"]
    if len(expected_receipts) != count:
        raise ValueError("native_generation_count_mismatch")
    consumed, budgets = [], set()
    projections = []
    for offset, candidate in enumerate(candidates):
        generation, execution, evaluation = rows[1 + offset * 3:4 + offset * 3]
        binding = generation["binding"]
        if set(binding) != {"run_id", "task_id", "budget_id", "wire_run_id", "wire_task_id",
                            "max_tool_steps", "candidate_id", "bundle_sha256", "payload_sha256"}:
            raise ValueError("native_generation_binding_invalid")
        budget_id = binding["budget_id"]
        if (budget_id in budgets or binding["run_id"] != child_id or binding["task_id"] != task_id
                or binding["candidate_id"] != candidate.candidate_id
                or binding["bundle_sha256"] != candidate.bundle_evidence["bundle_sha256"]
                or binding["max_tool_steps"] != default_manifest()["budgets"]["candidate_steps"]):
            raise ValueError("native_generation_binding_invalid")
        budgets.add(budget_id)
        receipt = candidate_generation_receipt(
            child_events, run_id=child_id, task_id=task_id, budget_id=budget_id,
            candidate_id=candidate.candidate_id, bundle_sha256=binding["bundle_sha256"],
            max_tool_steps=binding["max_tool_steps"],
        )
        if not receipt["completion"] or receipt["diagnostic_sha256"] != binding["payload_sha256"]:
            raise ValueError("native_generation_unverified")
        owned = [row for row in requests[3:] if row.get("budget_id") == budget_id]
        if not owned or any(row.get("run_id") != binding["wire_run_id"]
                            or row.get("task_id") != binding["wire_task_id"] for row in owned):
            raise ValueError("native_request_identity_mismatch")
        indices = [row["index"] for row in owned]
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError("native_request_order_invalid")
        for row in owned:
            start = row.get("started_elapsed_seconds")
            if start is None or not generation["started_at"] <= start <= start + row["elapsed_seconds"] <= generation["finished_at"]:
                raise ValueError("native_request_time_mismatch")
        consumed.extend(indices)
        evidence = candidate.bundle_evidence
        if (execution["binding"] != {key: evidence[key] for key in (
                "admission_sha256", "plan_sha256", "completion_sha256")}
                or evaluation["binding"] != {key: evidence[key] for key in (
                    "admission_sha256", "plan_sha256", "evaluation_sha256")}):
            raise ValueError("native_execution_evaluation_mismatch")
        projections.append({"candidate_id": candidate.candidate_id, "budget_id": budget_id,
                            "request_indices": indices, "generation": receipt,
                            "execution_sha256": evidence["completion_sha256"],
                            "evaluation_sha256": evidence["evaluation_sha256"]})
    if consumed != [row["index"] for row in requests[3:]]:
        raise ValueError("native_request_unaccounted")
    return {"closure_verified": True, "completed_candidates": count,
            "closure_sha256": anchor["sha256"], "stage_receipts": rows,
            "native_candidates": projections, "selected_candidate_id": identity["candidate_id"],
            "preparation_sha256": _sha(preparation)}
