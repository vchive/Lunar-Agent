"""Fixed small tasks and a model-independent acceptance oracle.

The oracle reads only registered JSON inputs and delivered JSON outputs. It does
not consume the generated contract, evaluator, score, or solver source. Feasible
suboptimal outputs are valid; exhaustive search supplies a separate optimum.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations, product

_COMMON_GOAL = """
Use only Python's standard library. Deliver a complete source bundle containing
at least two Python source files: an entrypoint and an imported helper module.
The two-source-file requirement is checked separately on delivered source, not
as an output feasibility constraint. Read every registered input from its exact
filename and produce both required JSON outputs at the declared output/ paths.
Do not add input files or require external dependencies. All IDs are exact,
case-sensitive strings. All reported counts, weights, loads and values must be
JSON integers (booleans and floating-point values are not integers). Empty
selections are feasible. Feasible suboptimal solutions remain valid; maximize
the independently recomputed total value. The quality objective is total_value,
with larger values better. There is no optimality hard constraint. Do not trust
or use a submitted summary as the authority for feasibility or quality. No
clarification or extra business assumptions are needed.
""".strip()


CASES = {
    "budget_selection": {
        "goal": """Solve a 0-1 budgeted selection problem (problem type packing).
The exact registered inputs are items.json and limits.json, both JSON objects.
items.json contains an items array; every item has id (string), weight (positive
integer), and value (positive integer). limits.json contains capacity and
max_items, both nonnegative integers. Choose any subset of the listed items.
Each selected ID must exist and appear at most once. The sum of selected weights
must be at most capacity and the number selected must be at most max_items.
Maximize the sum of selected values.
Write output/result.json as exactly {"selected_ids": [<item ID strings>]}.
Write output/summary.json as exactly {"total_value": <integer>,
"total_weight": <integer>, "item_count": <integer>}.
Both outputs are required JSON objects, and the summary must exactly match the
independent totals obtained from selected_ids and items.json. Output field
types, recognized unique IDs, capacity, item count limit, and summary agreement
are hard constraints. No other feasibility rule applies.
""" + _COMMON_GOAL,
        "inputs": {
            "items.json": {
                "items": [
                    {"id": "A", "weight": 2, "value": 6},
                    {"id": "B", "weight": 3, "value": 7},
                    {"id": "C", "weight": 4, "value": 9},
                    {"id": "D", "weight": 5, "value": 12},
                    {"id": "E", "weight": 7, "value": 16},
                    {"id": "F", "weight": 1, "value": 2},
                    {"id": "G", "weight": 6, "value": 13},
                    {"id": "H", "weight": 4, "value": 10},
                    {"id": "I", "weight": 2, "value": 4},
                    {"id": "J", "weight": 8, "value": 17},
                ],
            },
            "limits.json": {"capacity": 15, "max_items": 4},
        },
    },
    "worker_assignment": {
        "goal": """Solve a capacity-constrained worker-job assignment problem
(problem type assignment). The exact registered inputs are jobs.json and
workers.json, both JSON objects. jobs.json contains a jobs array; every job has
id (string), hours (positive integer), and value (positive integer).
workers.json contains a workers array; each worker has id (string), capacity
(nonnegative integer hours), and eligible_jobs (an array of job ID strings).
Choose any subset of jobs and assign each selected job to one eligible worker.
Every output job ID and worker ID must exist. A job may occur at most once
across all assignments. A worker may receive multiple jobs, but the sum of
their job hours must not exceed that worker's capacity. Maximize the sum of
values of assigned jobs. There are no time intervals, precedence constraints,
per-worker job count limits, or requirements to assign every job or worker.
Write output/result.json as exactly {"assignments": [{"job_id": <string>,
"worker_id": <string>}, ...]}. Each assignment has exactly those two keys.
Write output/summary.json as exactly {"total_value": <integer>,
"total_hours": <integer>, "assigned_count": <integer>,
"worker_loads": {<every worker ID>: <integer hours>}}.
Both outputs are required JSON objects. Include every worker in worker_loads,
including unused workers with load zero. All summary fields must exactly match
independent totals recomputed from assignments, jobs.json and workers.json.
Output types, recognized unique job IDs and recognized workers, eligibility,
worker capacities, and summary agreement are hard constraints. No other
feasibility rule applies.
""" + _COMMON_GOAL,
        "inputs": {
            "jobs.json": {
                "jobs": [
                    {"id": "J1", "hours": 4, "value": 11},
                    {"id": "J2", "hours": 3, "value": 8},
                    {"id": "J3", "hours": 5, "value": 13},
                    {"id": "J4", "hours": 2, "value": 6},
                    {"id": "J5", "hours": 4, "value": 10},
                    {"id": "J6", "hours": 1, "value": 4},
                ],
            },
            "workers.json": {
                "workers": [
                    {"id": "W1", "capacity": 5, "eligible_jobs": ["J1", "J2", "J4", "J6"]},
                    {"id": "W2", "capacity": 5, "eligible_jobs": ["J2", "J3", "J5", "J6"]},
                    {"id": "W3", "capacity": 4, "eligible_jobs": ["J1", "J4", "J5", "J6"]},
                ],
            },
        },
    },
}


def _result(errors, quality=None):
    return {"validity": not errors, "quality": quality if not errors else None, "errors": errors}


def _fields(value, fields):
    return type(value) is dict and set(value) == set(fields)


def _integers(value, fields):
    return all(type(value.get(field)) is int for field in fields)


def _output_objects(outputs, result_fields, summary_fields):
    if not isinstance(outputs, dict):
        return None, None, ["outputs_type"]
    required = {"output/result.json", "output/summary.json"}
    if not required <= set(outputs):
        return None, None, ["missing_output"]
    result, summary = (outputs[name] for name in ("output/result.json", "output/summary.json"))
    errors = []
    if not _fields(result, result_fields):
        errors.append("result_schema")
    if not _fields(summary, summary_fields):
        errors.append("summary_schema")
    return result, summary, errors


def _selection_check(inputs, outputs):
    result, summary, errors = _output_objects(outputs, ("selected_ids",),
                                              ("total_value", "total_weight", "item_count"))
    if errors:
        return _result(errors)
    ids = result["selected_ids"]
    if type(ids) is not list or any(type(item) is not str for item in ids):
        return _result(["selected_ids_type"])
    if len(ids) != len(set(ids)):
        errors.append("duplicate_id")
    items = {item["id"]: item for item in inputs["items.json"]["items"]}
    if any(item not in items for item in ids):
        return _result([*errors, "unknown_id"])
    weight = sum(items[item]["weight"] for item in ids)
    value = sum(items[item]["value"] for item in ids)
    limits = inputs["limits.json"]
    if weight > limits["capacity"]:
        errors.append("capacity_exceeded")
    if len(ids) > limits["max_items"]:
        errors.append("item_limit_exceeded")
    if not _integers(summary, ("total_value", "total_weight", "item_count")):
        errors.append("summary_type")
    elif summary != {"total_value": value, "total_weight": weight, "item_count": len(ids)}:
        errors.append("summary_mismatch")
    return _result(errors, value)


def _assignment_check(inputs, outputs):
    summary_fields = ("total_value", "total_hours", "assigned_count", "worker_loads")
    result, summary, errors = _output_objects(outputs, ("assignments",), summary_fields)
    if errors:
        return _result(errors)
    assignments = result["assignments"]
    if (type(assignments) is not list or any(
            not _fields(row, ("job_id", "worker_id"))
            or type(row["job_id"]) is not str or type(row["worker_id"]) is not str
            for row in assignments)):
        return _result(["assignments_type"])
    jobs = {job["id"]: job for job in inputs["jobs.json"]["jobs"]}
    workers = {worker["id"]: worker for worker in inputs["workers.json"]["workers"]}
    job_ids = [row["job_id"] for row in assignments]
    if len(job_ids) != len(set(job_ids)):
        errors.append("duplicate_job")
    if any(row["job_id"] not in jobs for row in assignments):
        errors.append("unknown_job")
    if any(row["worker_id"] not in workers for row in assignments):
        errors.append("unknown_worker")
    if "unknown_job" in errors or "unknown_worker" in errors:
        return _result(errors)
    loads = dict.fromkeys(workers, 0)
    for row in assignments:
        worker_id, job_id = row["worker_id"], row["job_id"]
        if job_id not in workers[worker_id]["eligible_jobs"]:
            errors.append("ineligible_worker")
        loads[worker_id] += jobs[job_id]["hours"]
    if any(load > workers[worker_id]["capacity"] for worker_id, load in loads.items()):
        errors.append("capacity_exceeded")
    value = sum(jobs[job_id]["value"] for job_id in job_ids)
    reported_loads = summary["worker_loads"]
    if (not _integers(summary, ("total_value", "total_hours", "assigned_count"))
            or not _fields(reported_loads, workers)
            or not _integers(reported_loads, workers)):
        errors.append("summary_type")
    elif summary != {"total_value": value, "total_hours": sum(loads.values()),
                     "assigned_count": len(assignments), "worker_loads": loads}:
        errors.append("summary_mismatch")
    return _result(errors, value)


def check(case_key, inputs, outputs):
    """Check semantic feasibility and exact total value; invalid quality is null.

    ``inputs`` are the fixed, trusted task inputs (or a registered variant).
    ``outputs`` contain parsed JSON values. A caller must separately reject
    malformed JSON, duplicate JSON object keys, missing files and unsafe paths.
    """
    if case_key == "budget_selection":
        return _selection_check(inputs, outputs)
    if case_key == "worker_assignment":
        return _assignment_check(inputs, outputs)
    raise ValueError(f"unknown case: {case_key}")


def _selection_output(inputs, ids):
    items = {item["id"]: item for item in inputs["items.json"]["items"]}
    return {
        "output/result.json": {"selected_ids": list(ids)},
        "output/summary.json": {
            "total_value": sum(items[item]["value"] for item in ids),
            "total_weight": sum(items[item]["weight"] for item in ids),
            "item_count": len(ids),
        },
    }


def _assignment_output(inputs, pairs):
    jobs = {job["id"]: job for job in inputs["jobs.json"]["jobs"]}
    loads = {worker["id"]: 0 for worker in inputs["workers.json"]["workers"]}
    for job_id, worker_id in pairs:
        loads[worker_id] += jobs[job_id]["hours"]
    return {
        "output/result.json": {
            "assignments": [{"job_id": job_id, "worker_id": worker_id} for job_id, worker_id in pairs],
        },
        "output/summary.json": {
            "total_value": sum(jobs[job_id]["value"] for job_id, _ in pairs),
            "total_hours": sum(loads.values()), "assigned_count": len(pairs), "worker_loads": loads,
        },
    }


def _best_outputs(case_key, inputs):
    # Direct exhaustive feasibility rules are deliberately independent of check().
    if case_key == "budget_selection":
        items, limits = inputs["items.json"]["items"], inputs["limits.json"]
        best, score = (), 0
        for count in range(min(len(items), limits["max_items"]) + 1):
            for selected in combinations(items, count):
                value = sum(item["value"] for item in selected)
                if sum(item["weight"] for item in selected) <= limits["capacity"] and value > score:
                    best, score = tuple(item["id"] for item in selected), value
        return _selection_output(inputs, best)
    if case_key == "worker_assignment":
        jobs, workers = inputs["jobs.json"]["jobs"], inputs["workers.json"]["workers"]
        choices = [(None, *(i for i, worker in enumerate(workers) if job["id"] in worker["eligible_jobs"]))
                   for job in jobs]
        best, score = (), 0
        for assignment in product(*choices):
            loads = [0] * len(workers)
            value, pairs = 0, []
            for job, worker_index in zip(jobs, assignment, strict=True):
                if worker_index is not None:
                    loads[worker_index] += job["hours"]
                    value += job["value"]
                    pairs.append((job["id"], workers[worker_index]["id"]))
            if value > score and all(load <= worker["capacity"] for load, worker in zip(loads, workers, strict=True)):
                best, score = tuple(pairs), value
        return _assignment_output(inputs, best)
    raise ValueError(f"unknown case: {case_key}")


def optimum(case_key, inputs):
    """Return the exact optimum obtained by enumerating every allowed choice."""
    return _best_outputs(case_key, inputs)["output/summary.json"]["total_value"]


def holdouts(case_key):
    """Return twelve frozen-design, independently labelled evaluator probes.

    Three feasible probes include one changed-input generalization check. Nine
    infeasible probes attack semantic constraints, forged summaries and missing
    output handling. These probes must not be shown to model participants.
    """
    inputs = deepcopy(CASES[case_key]["inputs"])
    best = _best_outputs(case_key, inputs)
    if case_key == "budget_selection":
        low = _selection_output(inputs, ["F"])
        variant = deepcopy(inputs)
        variant["limits.json"] = {"capacity": 2, "max_items": 1}
        variant["items.json"]["items"][8]["value"] = 20
        invalid = [
            ("duplicate_id", _selection_output(inputs, ["A", "A"])),
            ("unknown_id", {**deepcopy(low), "output/result.json": {"selected_ids": ["unknown"]}}),
            ("capacity_exceeded", _selection_output(inputs, ["E", "G", "J"])),
            ("item_limit_exceeded", _selection_output(inputs, ["A", "B", "F", "H", "I"])),
        ]
        for name, field in (("summary_value_forged", "total_value"), ("summary_weight_wrong", "total_weight"),
                            ("summary_count_wrong", "item_count")):
            output = deepcopy(low)
            output["output/summary.json"][field] += 1000
            invalid.append((name, output))
        output = deepcopy(low)
        output["output/summary.json"]["item_count"] = True
        invalid.append(("boolean_summary", output))
    elif case_key == "worker_assignment":
        low = _assignment_output(inputs, [("J6", "W1")])
        variant = deepcopy(inputs)
        variant["workers.json"]["workers"][0]["capacity"] = 1
        variant["workers.json"]["workers"][1]["capacity"] = 0
        variant["workers.json"]["workers"][2]["capacity"] = 0
        variant["jobs.json"]["jobs"][5]["value"] = 25
        invalid = [
            ("duplicate_job", _assignment_output(inputs, [("J6", "W1"), ("J6", "W2")])),
            ("unknown_job", {**deepcopy(low), "output/result.json": {
                "assignments": [{"job_id": "unknown", "worker_id": "W1"}],
            }}),
            ("unknown_worker", {**deepcopy(low), "output/result.json": {
                "assignments": [{"job_id": "J6", "worker_id": "unknown"}],
            }}),
            ("ineligible_worker", _assignment_output(inputs, [("J5", "W1")])),
            ("capacity_exceeded", _assignment_output(inputs, [("J1", "W1"), ("J2", "W1")])),
        ]
        output = deepcopy(low)
        output["output/summary.json"]["total_value"] += 1000
        invalid.append(("summary_value_forged", output))
        output = deepcopy(low)
        output["output/summary.json"]["worker_loads"]["W2"] = 1
        invalid.append(("summary_load_wrong", output))
        output = deepcopy(low)
        output["output/result.json"]["assignments"][0]["job_id"] = True
        invalid.append(("assignment_type", output))
    else:
        raise ValueError(f"unknown case: {case_key}")
    invalid.append(("missing_output", {"output/result.json": deepcopy(low["output/result.json"])}))
    rows = [("feasible_suboptimal", inputs, low), ("feasible_optimal", inputs, best),
            ("feasible_changed_inputs", variant, _best_outputs(case_key, variant))]
    rows.extend((name, inputs, output) for name, output in invalid)
    return [{"name": name, "inputs": deepcopy(probe_inputs), "outputs": deepcopy(outputs),
             "expected": check(case_key, probe_inputs, outputs)} for name, probe_inputs, outputs in rows]
