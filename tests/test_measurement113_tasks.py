"""The registered acceptance oracle must reject plausible evaluator shortcuts."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "specs/113-real-multifile-acceptance/measurement/tasks.py"
_SPEC = importlib.util.spec_from_file_location("measurement113_tasks", _PATH)
tasks = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tasks)


@pytest.mark.parametrize(("case_key", "expected"), [("budget_selection", 37), ("worker_assignment", 39)])
def test_exact_fixed_optimum(case_key, expected):
    assert tasks.optimum(case_key, tasks.CASES[case_key]["inputs"]) == expected


def test_selection_boundary_and_suboptimal_are_valid():
    inputs = tasks.CASES["budget_selection"]["inputs"]
    output = {
        "output/result.json": {"selected_ids": ["A", "C", "D", "H"]},
        "output/summary.json": {"total_value": 37, "total_weight": 15, "item_count": 4},
    }
    assert tasks.check("budget_selection", inputs, output) == {"validity": True, "quality": 37, "errors": []}
    output = {
        "output/result.json": {"selected_ids": ["A"]},
        "output/summary.json": {"total_value": 6, "total_weight": 2, "item_count": 1},
    }
    assert tasks.check("budget_selection", inputs, output) == {"validity": True, "quality": 6, "errors": []}


def test_assignment_boundary_and_unused_worker_are_valid():
    inputs = tasks.CASES["worker_assignment"]["inputs"]
    output = {
        "output/result.json": {"assignments": [{"job_id": "J3", "worker_id": "W2"}]},
        "output/summary.json": {"total_value": 13, "total_hours": 5, "assigned_count": 1,
                                "worker_loads": {"W1": 0, "W2": 5, "W3": 0}},
    }
    assert tasks.check("worker_assignment", inputs, output) == {"validity": True, "quality": 13, "errors": []}


@pytest.mark.parametrize("case_key", tasks.CASES)
def test_empty_selection_is_feasible(case_key):
    if case_key == "budget_selection":
        output = {"output/result.json": {"selected_ids": []},
                  "output/summary.json": {"total_value": 0, "total_weight": 0, "item_count": 0}}
    else:
        output = {"output/result.json": {"assignments": []},
                  "output/summary.json": {"total_value": 0, "total_hours": 0, "assigned_count": 0,
                                          "worker_loads": {"W1": 0, "W2": 0, "W3": 0}}}
    assert tasks.check(case_key, tasks.CASES[case_key]["inputs"], output) == {
        "validity": True, "quality": 0, "errors": [],
    }


@pytest.mark.parametrize(("case_key", "valid_scores"), [
    ("budget_selection", [2, 37, 20]), ("worker_assignment", [4, 39, 25]),
])
def test_holdout_denominators_labels_and_quality_are_fixed(case_key, valid_scores):
    probes = tasks.holdouts(case_key)
    assert len(probes) == len({probe["name"] for probe in probes}) == 12
    assert [probe["name"] for probe in probes[:3]] == [
        "feasible_suboptimal", "feasible_optimal", "feasible_changed_inputs",
    ]
    assert [probe["expected"]["quality"] for probe in probes] == valid_scores + [None] * 9
    assert [probe["expected"]["validity"] for probe in probes] == [True] * 3 + [False] * 9
    assert probes[2]["inputs"] != tasks.CASES[case_key]["inputs"]
    assert probes[-1]["name"] == "missing_output"
    for probe in probes:
        before = deepcopy(probe)
        assert tasks.check(case_key, probe["inputs"], probe["outputs"]) == probe["expected"]
        assert probe == before
    probes[0]["inputs"].clear()
    assert tasks.holdouts(case_key)[0]["inputs"] == tasks.CASES[case_key]["inputs"]


@pytest.mark.parametrize("case_key", tasks.CASES)
@pytest.mark.parametrize("bad_value", [True, 4.0, float("nan"), float("inf"), "4", None, [], {}])
def test_reported_value_requires_exact_integer(case_key, bad_value):
    probe = tasks.holdouts(case_key)[0]
    probe["outputs"]["output/summary.json"]["total_value"] = bad_value
    checked = tasks.check(case_key, probe["inputs"], probe["outputs"])
    assert checked["validity"] is False
    assert checked["quality"] is None
    assert "summary_type" in checked["errors"]


@pytest.mark.parametrize("case_key", tasks.CASES)
@pytest.mark.parametrize("path", ["output/result.json", "output/summary.json"])
@pytest.mark.parametrize("bad_value", [None, [], "bad", 1, {"unexpected": 1}])
def test_malformed_output_objects_never_receive_quality(case_key, path, bad_value):
    probe = tasks.holdouts(case_key)[0]
    probe["outputs"][path] = bad_value
    checked = tasks.check(case_key, probe["inputs"], probe["outputs"])
    assert checked["validity"] is False
    assert checked["quality"] is None


@pytest.mark.parametrize("bad_ids", [None, "A", [True], [1], [{}], [["A"]]])
def test_selection_id_types_are_checked_before_lookup(bad_ids):
    probe = tasks.holdouts("budget_selection")[0]
    probe["outputs"]["output/result.json"]["selected_ids"] = bad_ids
    assert tasks.check("budget_selection", probe["inputs"], probe["outputs"])["errors"] == ["selected_ids_type"]


@pytest.mark.parametrize("bad_assignments", [None, {}, [None], [{}], [{"job_id": []}],
    [{"job_id": "J6", "worker_id": {}}], [{"job_id": "J6", "worker_id": "W1", "value": 1000}],
])
def test_assignment_schema_is_checked_before_lookup(bad_assignments):
    probe = tasks.holdouts("worker_assignment")[0]
    probe["outputs"]["output/result.json"]["assignments"] = bad_assignments
    assert tasks.check("worker_assignment", probe["inputs"], probe["outputs"])["errors"] == ["assignments_type"]


@pytest.mark.parametrize("bad_loads", [{"W1": 1}, {"W1": True, "W2": 0, "W3": 0},
    {"W1": 1, "W2": 0, "W3": 0, "fake": 0}, [], None,
])
def test_assignment_summary_requires_every_worker_and_strict_loads(bad_loads):
    probe = tasks.holdouts("worker_assignment")[0]
    probe["outputs"]["output/summary.json"]["worker_loads"] = bad_loads
    assert tasks.check("worker_assignment", probe["inputs"], probe["outputs"])["errors"] == ["summary_type"]


@pytest.mark.parametrize(("case_key", "input_file", "array", "value_field"), [
    ("budget_selection", "items.json", "items", "value"),
    ("worker_assignment", "jobs.json", "jobs", "value"),
])
def test_oracle_recomputes_value_from_variant_inputs(case_key, input_file, array, value_field):
    probe = tasks.holdouts(case_key)[0]
    # The low probe selects F/J6, both the sixth record, and reports its original value.
    probe["inputs"][input_file][array][5][value_field] += 1
    checked = tasks.check(case_key, probe["inputs"], probe["outputs"])
    assert checked == {"validity": False, "quality": None, "errors": ["summary_mismatch"]}


@pytest.mark.parametrize("case_key", tasks.CASES)
def test_oracle_never_consumes_generated_score_claims(case_key):
    probe = tasks.holdouts(case_key)[0]
    probe["outputs"]["evaluator-report.json"] = {"validity": 1, "quality": 999999, "combined_score": 999999}
    assert tasks.check(case_key, probe["inputs"], probe["outputs"]) == probe["expected"]
