"""Offline receipts bind complete plan identities without changing legacy receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import benchmark_result
from lunar_evolution.benchmark_comparison import BenchmarkComparisonPlan
from lunar_evolution.benchmark_result import (
    BenchmarkComparisonResult,
    BenchmarkResultError,
    ComparisonArmResult,
    admit_benchmark_comparison_result,
    bind_benchmark_comparison_result_evidence,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_comparison import env


def _plan() -> BenchmarkComparisonPlan:
    return BenchmarkComparisonPlan.from_envelopes({"sky": env(), "llm4ad": env("llm4ad")})


def _arms(*, descriptors: bool = False) -> tuple[ComparisonArmResult, ...]:
    return tuple(
        ComparisonArmResult(
            arm_id, "completed", 10, 2, 1, 0.5, "e" * 64,
            f"{arm_id}.json" if descriptors else None,
            17 if descriptors else None,
        )
        for arm_id in ("sky", "llm4ad")
    )


def _variant(plan: BenchmarkComparisonPlan, change: str) -> BenchmarkComparisonPlan:
    value = plan.to_dict()
    if change == "swap":
        first, second = value["arms"]
        first["envelope"], second["envelope"] = second["envelope"], first["envelope"]
    else:
        value["arms"][0]["envelope"]["benchmark"][change] = {
            "name": "other",
            "release_version": "v2",
            "publication_digest": "sha256:" + "f" * 64,
        }[change]
    return BenchmarkComparisonPlan.from_dict(value)


@pytest.mark.parametrize(
    ("descriptors", "result_id", "receipt_digest"),
    [
        (
            False,
            "c9f5a3a8cc4c14ee7cd01c4ba32e6383620d40c5f1075da2f978cfb27adae357",
            "87c88bd07fd4cbaa4e9bc6ba261f5029e44fcd025b3c0301ae840a674ef72871",
        ),
        (
            True,
            "c9f20a721905ced6d1354552d9a718ce04ad2adba7d86ff17bc0ad5d7ee8be61",
            "bb10ddfcb7795acdfb8ba0ffe635260aa26e6b19743f423e1d7c6ea21aeee99d",
        ),
    ],
)
def test_legacy_receipt_golden_bytes_and_identity(descriptors, result_id, receipt_digest):
    # IDs/digests were recorded from d81145f for both 099 and 100 representations.
    plan = _plan()
    result = BenchmarkComparisonResult(plan.comparison_id, result_id, _arms(descriptors=descriptors))
    assert result.result_id == result_id
    assert result.digest() == receipt_digest
    assert "plan_sha256" not in result.to_dict()
    assert parse_benchmark_comparison_result(result.to_dict()) == result
    assert admit_benchmark_comparison_result(result, plan) == result


def test_from_plan_and_admission_are_structural_without_optional_files(monkeypatch):
    plan = _plan()
    monkeypatch.setattr(
        benchmark_result.os, "open", lambda *_args, **_kwargs: pytest.fail("opened a file")
    )
    result = BenchmarkComparisonResult.from_plan(plan, _arms(descriptors=True))
    assert result.plan_sha256 == plan.digest()
    assert parse_benchmark_comparison_result(result.to_dict()) == result
    assert admit_benchmark_comparison_result(
        result, plan, expected_plan_sha256=plan.digest()
    ) == result


@pytest.mark.parametrize("change", ["name", "release_version", "publication_digest", "swap"])
def test_plan_pin_rejects_same_named_arms_with_different_envelopes(change):
    plan = _plan()
    other = _variant(plan, change)
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    assert other.comparison_id == plan.comparison_id
    assert other.digest() != plan.digest()
    assert {arm.id for arm in other.arms} == {arm.id for arm in plan.arms}
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        admit_benchmark_comparison_result(result, other)
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        admit_benchmark_comparison_result(result, other, expected_plan_sha256=other.digest())
    changed = BenchmarkComparisonResult.from_plan(other, _arms())
    assert changed.result_id != result.result_id


def test_legacy_receipt_requires_a_pin_when_caller_supplies_one():
    plan = _plan()
    legacy = BenchmarkComparisonResult(
        plan.comparison_id,
        "c9f5a3a8cc4c14ee7cd01c4ba32e6383620d40c5f1075da2f978cfb27adae357",
        _arms(),
    )
    other = _variant(plan, "release_version")
    # Legacy admission intentionally retains its common-identity-only compatibility.
    assert admit_benchmark_comparison_result(legacy, other) == legacy
    for supplied_plan in (plan, other):
        with pytest.raises(BenchmarkResultError, match="benchmark_result_plan_pin_required"):
            admit_benchmark_comparison_result(
                legacy, supplied_plan, expected_plan_sha256=supplied_plan.digest()
            )


def test_caller_pin_rejects_receipt_and_plan_changed_together():
    plan = _plan()
    other = _variant(plan, "publication_digest")
    result = BenchmarkComparisonResult.from_plan(other, _arms())
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        admit_benchmark_comparison_result(result, other, expected_plan_sha256=plan.digest())


def test_arm_order_does_not_change_plan_pin_or_result_identity():
    plan = _plan()
    value = plan.to_dict()
    value["arms"].reverse()
    reordered = BenchmarkComparisonPlan.from_dict(value)
    first = BenchmarkComparisonResult.from_plan(plan, _arms())
    second = BenchmarkComparisonResult.from_plan(reordered, tuple(reversed(_arms())))
    assert first == second
    assert first.digest() == second.digest()
    assert admit_benchmark_comparison_result(
        first, reordered, expected_plan_sha256=plan.digest()
    ) == first


@pytest.mark.parametrize("change", ["alter", "remove", "legacy_add"])
def test_plan_pin_participates_in_result_identity(change):
    plan = _plan()
    value = BenchmarkComparisonResult.from_plan(plan, _arms()).to_dict()
    if change == "alter":
        value["plan_sha256"] = "f" * 64
    elif change == "remove":
        del value["plan_sha256"]
    else:
        value["result_id"] = "c9f5a3a8cc4c14ee7cd01c4ba32e6383620d40c5f1075da2f978cfb27adae357"
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        parse_benchmark_comparison_result(value)


@pytest.mark.parametrize("value", [None, "", "A" * 64, "sha256:" + "a" * 64, True, 17, [], {}])
def test_result_rejects_invalid_or_explicit_null_plan_pin(value):
    payload = BenchmarkComparisonResult.from_plan(_plan(), _arms()).to_dict()
    payload["plan_sha256"] = value
    with pytest.raises(BenchmarkResultError, match="benchmark_result_invalid"):
        parse_benchmark_comparison_result(payload)


@pytest.mark.parametrize("value", ["", "A" * 64, "sha256:" + "a" * 64, True, 17, [], {}])
def test_admission_rejects_malformed_caller_pin(value):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    with pytest.raises(BenchmarkResultError, match="benchmark_result_invalid"):
        admit_benchmark_comparison_result(result, plan, expected_plan_sha256=value)


@pytest.mark.parametrize("operation", ["factory", "admission"])
@pytest.mark.parametrize("change", ["protocol", "duplicate_arm", "candidate_drift"])
def test_result_paths_revalidate_plan_structure(operation, change):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    if change == "protocol":
        object.__setattr__(plan, "protocol", "other")
    elif change == "duplicate_arm":
        object.__setattr__(plan, "arms", (plan.arms[0], plan.arms[0]))
    else:
        plan.arms[0].envelope.candidate["filename"] = "different.py"
    with pytest.raises(BenchmarkResultError, match="benchmark_result_invalid"):
        if operation == "factory":
            BenchmarkComparisonResult.from_plan(plan, _arms())
        else:
            admit_benchmark_comparison_result(result, plan)


@pytest.mark.parametrize("operation", ["factory", "admission"])
def test_result_paths_reject_non_plan_objects(operation):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    with pytest.raises(BenchmarkResultError, match="benchmark_result_invalid"):
        if operation == "factory":
            BenchmarkComparisonResult.from_plan(None, _arms())
        else:
            admit_benchmark_comparison_result(result, None)


@pytest.mark.parametrize("change", ["pin", "arm", "result_id"])
def test_admission_revalidates_mutated_result_object(change):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    if change == "pin":
        object.__setattr__(result, "plan_sha256", None)
    elif change == "arm":
        object.__setattr__(result.arms[0], "best_score", float("nan"))
    else:
        object.__setattr__(result, "result_id", "f" * 64)
    with pytest.raises(BenchmarkResultError):
        admit_benchmark_comparison_result(result, plan)


def test_from_plan_rejects_unmatched_arm_names():
    arms = _arms()
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        BenchmarkComparisonResult.from_plan(_plan(), (replace(arms[0], arm_id="other"), arms[1]))


def test_factory_result_still_requires_explicit_evidence_binding(tmp_path: Path):
    plan = _plan()
    payload = b"comparison evidence\n"
    digest = hashlib.sha256(payload).hexdigest()
    arms = tuple(
        replace(arm, evidence_path=f"{arm.arm_id}.json", evidence_size=len(payload),
                evidence_sha256=digest)
        for arm in _arms()
    )
    result = BenchmarkComparisonResult.from_plan(plan, arms)
    with pytest.raises(BenchmarkResultError, match="benchmark_result_evidence_missing"):
        bind_benchmark_comparison_result_evidence(
            result, plan, tmp_path, expected_plan_sha256=plan.digest()
        )
    for arm in arms:
        (tmp_path / arm.evidence_path).write_bytes(payload)
    assert bind_benchmark_comparison_result_evidence(
        result, plan, tmp_path, expected_plan_sha256=plan.digest()
    ) == result
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        bind_benchmark_comparison_result_evidence(
            result, plan, tmp_path, expected_plan_sha256="f" * 64
        )


def test_plan_mismatch_is_rejected_before_evidence_reads(monkeypatch, tmp_path: Path):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms(descriptors=True))
    monkeypatch.setattr(
        benchmark_result, "_verify_evidence",
        lambda *_args: pytest.fail("evidence was read before rejecting the plan"),
    )
    with pytest.raises(BenchmarkResultError, match="benchmark_result_identity_mismatch"):
        admit_benchmark_comparison_result(
            result, plan, evidence_root=tmp_path, expected_plan_sha256="f" * 64
        )


def test_pinned_receipt_file_roundtrip(tmp_path: Path):
    plan = _plan()
    result = BenchmarkComparisonResult.from_plan(plan, _arms())
    receipt = tmp_path / "result.json"
    receipt.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    assert admit_benchmark_comparison_result(
        receipt, plan, expected_plan_sha256=plan.digest()
    ) == result
