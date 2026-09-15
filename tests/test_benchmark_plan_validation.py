"""Plan identity is revalidated before any input admission or result binding."""

import os
from dataclasses import replace

import pytest

from famou import benchmark_comparison as module
from famou.benchmark_comparison import (
    BenchmarkComparisonError,
    BenchmarkComparisonPlan,
    ComparisonArm,
    admit_benchmark_comparison_plan,
    validate_benchmark_comparison_plan,
)
from famou.benchmark_task import (
    BenchmarkTaskError,
    PhysicalAttemptBudget,
    TaskInput,
)
from tests.test_benchmark_comparison import env


def _plan():
    return BenchmarkComparisonPlan.from_envelopes({"sky": env(), "llm4ad": env("llm4ad")})


@pytest.mark.parametrize(
    "mutation",
    [
        "schema", "protocol", "comparison_id", "duplicate_arm", "single_arm", "too_many_arms",
        "missing_arms", "invalid_arm", "invalid_arm_id", "missing_envelope", "invalid_envelope",
        "invalid_timeout", "invalid_common", "drifted_common",
    ],
)
def test_mutated_plan_is_rejected_before_input_admission(monkeypatch, mutation):
    plan = _plan()
    if mutation == "schema":
        object.__setattr__(plan, "schema_version", "unknown")
    elif mutation == "protocol":
        object.__setattr__(plan, "protocol", "unknown")
    elif mutation == "comparison_id":
        object.__setattr__(plan, "comparison_id", "different")
    elif mutation == "duplicate_arm":
        object.__setattr__(plan, "arms", (plan.arms[0], plan.arms[0]))
    elif mutation == "single_arm":
        object.__setattr__(plan, "arms", (plan.arms[0],))
    elif mutation == "too_many_arms":
        object.__setattr__(plan, "arms", tuple(ComparisonArm(f"arm-{i}", env()) for i in range(17)))
    elif mutation == "missing_arms":
        object.__setattr__(plan, "arms", None)
    elif mutation == "invalid_arm":
        object.__setattr__(plan, "arms", (None, None))
    elif mutation == "invalid_arm_id":
        object.__setattr__(plan.arms[0], "id", "invalid/arm")
    elif mutation == "missing_envelope":
        object.__setattr__(plan.arms[0], "envelope", None)
    elif mutation == "invalid_envelope":
        object.__setattr__(plan.arms[0].envelope, "schema_version", "unknown")
    elif mutation == "invalid_timeout":
        object.__setattr__(plan.arms[0].envelope.budget, "timeout_seconds", 10**400)
    elif mutation == "invalid_common":
        object.__setattr__(plan, "common", None)
    else:
        plan.common["candidate"]["filename"] = "other.py"
        object.__setattr__(plan, "comparison_id", module._derived_id(plan.common))

    monkeypatch.setattr(
        module, "admit_benchmark_task_envelope", lambda *args, **kwargs: pytest.fail("read inputs"),
    )
    with pytest.raises(BenchmarkComparisonError):
        validate_benchmark_comparison_plan(plan)
    with pytest.raises(BenchmarkComparisonError):
        admit_benchmark_comparison_plan(
            plan, contract_sha256="c" * 64, input_root="unused", model_profile_sha256="d" * 64,
            evaluator_fingerprint="b" * 64,
        )


def test_validation_returns_detached_plan_without_io(monkeypatch):
    plan = _plan()
    digest = plan.digest()
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("opened a file"))
    validated = validate_benchmark_comparison_plan(plan)
    assert validated.to_dict() == plan.to_dict()
    assert validated is not plan
    assert validated.arms[0].envelope is not plan.arms[0].envelope
    validated.common["model"]["requested"] = "changed"
    validated.arms[0].envelope.benchmark["release_version"] = "changed"
    assert plan.digest() == digest


def test_draft_with_mismatched_arms_is_rejected_by_validation():
    # Draft construction is retained for callers that use admission to diagnose a plan.
    second = replace(env("llm4ad"), candidate={"kind": "single_file", "filename": "other.py"})
    plan = BenchmarkComparisonPlan.from_envelopes({"sky": env(), "llm4ad": second})
    with pytest.raises(BenchmarkComparisonError, match="^benchmark_comparison_identity_mismatch$"):
        validate_benchmark_comparison_plan(plan)


@pytest.mark.parametrize("arms", [None, 42, "invalid", [], (), [None, None]])
def test_plan_constructor_rejects_invalid_arm_container(arms):
    plan = _plan()
    with pytest.raises(BenchmarkComparisonError, match="^benchmark_comparison_invalid$"):
        replace(plan, arms=arms)


def test_plan_and_task_container_inputs_are_frozen():
    plan = _plan()
    supplied_arms = list(plan.arms)
    copied_plan = replace(plan, arms=supplied_arms)
    supplied_arms.clear()
    assert len(copied_plan.arms) == 2
    supplied_inputs = list(env().inputs)
    copied_env = replace(env(), inputs=supplied_inputs)
    supplied_inputs.clear()
    assert len(copied_env.inputs) == 1


@pytest.mark.parametrize("field", ["task", "model", "evaluator", "budget", "inputs"])
def test_envelope_constructor_rejects_invalid_nested_dto(field):
    with pytest.raises(BenchmarkTaskError, match="^benchmark_task_envelope_invalid$"):
        replace(env(), **{field: None})


def test_task_path_and_oversized_timeout_have_fixed_errors():
    with pytest.raises(BenchmarkTaskError, match="^benchmark_task_envelope_invalid$"):
        TaskInput(".", 0, "a" * 64)
    with pytest.raises(BenchmarkTaskError, match="^benchmark_task_envelope_invalid$"):
        PhysicalAttemptBudget(1, 10**400)
