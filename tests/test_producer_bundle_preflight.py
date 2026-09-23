from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_preflight import (
    ProducerBundlePreflightError,
    compute_archive_prefix_digest,
    derive_producer_bundle_candidate_id,
    parse_producer_bundle_preflight_receipt,
    preflight_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
)


def _d(letter: str) -> str:
    return letter * 64


def _plan() -> ProducerBundleAdmissionPlan:
    item = ProducerBundleAdmissionItem(
        bundle_id="bundle-1", bundle_sha256=_d("a"), draft_bundle_sha256=_d("a"),
        entrypoint="main.py", material_paths=("main.py",), producer_fingerprint=_d("b"),
    )
    return ProducerBundleAdmissionPlan(
        contract_sha256=_d("0"), evaluator_kind="callback", evaluator_fingerprint=_d("1"),
        runner_fingerprint=_d("2"), dependency_sha256=_d("3"), environment_sha256=_d("4"),
        bundles=(item,),
    )


def _journal(plan: ProducerBundleAdmissionPlan):
    empty = hashlib.sha256(b"").hexdigest()
    config = {"strategy": "population", "num_islands": 1}
    active_ids = {"0": []}
    state = {"strategy": "population", "config": config, "active_ids": active_ids}
    state_bytes = json.dumps(state, sort_keys=True).encode()
    state_sha = hashlib.sha256(state_bytes).hexdigest()
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    active_ids_sha = hashlib.sha256(json.dumps(active_ids, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return build_producer_bundle_publication_journal(
        journal_id="journal-1", run_id="run-1", parent_task_id="parent-1", task_id="task-1",
        admission_sha256=plan.digest(), archive_prefix_sha256=compute_archive_prefix_digest(
            empty, state_sha, strategy_config_sha256=config_sha, active_ids_sha256=active_ids_sha,
        ), base_archive_sha256=empty, base_state_sha256=state_sha, contract_sha256=plan.contract_sha256,
        evaluator_kind=plan.evaluator_kind, evaluator_fingerprint=plan.evaluator_fingerprint,
        runner_fingerprint=plan.runner_fingerprint, dependency_sha256=plan.dependency_sha256,
        environment_sha256=plan.environment_sha256, budget_sha256=_d("5"), strategy="population",
        population_config_sha256=config_sha, num_islands=1,
        candidates=(ProducerBundlePublicationCandidate(
            candidate_id=derive_producer_bundle_candidate_id("journal-1", 0, "bundle-1", _d("a")), bundle_id="bundle-1", bundle_sha256=_d("a"), parent_id=None,
            generation=0, iteration=0, island_id=0, preparation_receipt_sha256=_d("7"),
        ),),
    )


def _workspace(tmp_path: Path, journal_id: str = "journal-1") -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "evolution" / "producer-batches" / journal_id).mkdir(parents=True)
    state = {"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": []}}
    (workspace / "evolution" / "state.json").write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    (workspace / "evolution" / "archive.jsonl").write_text("", encoding="utf-8")
    return workspace


def test_missing_batch_path_is_rejected_without_allocation(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = tmp_path / "missing"
    before = tuple(tmp_path.rglob("*"))
    with pytest.raises(ProducerBundlePreflightError) as caught:
        preflight_producer_bundle_publication(
            workspace, plan, journal, budget_sha256=journal.budget_sha256,
        )
    assert caught.value.code == "producer_bundle_preflight_workspace_invalid"
    assert tuple(tmp_path.rglob("*")) == before


def test_unsafe_derived_batch_path_is_rejected(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = _workspace(tmp_path)
    batches = workspace / "evolution" / "producer-batches"
    target = tmp_path / "outside"
    target.mkdir()
    (batches / journal.journal_id).rmdir()
    (batches / journal.journal_id).symlink_to(target, target_is_directory=True)
    with pytest.raises(ProducerBundlePreflightError) as caught:
        preflight_producer_bundle_publication(
            workspace, plan, journal, budget_sha256=journal.budget_sha256,
        )
    assert caught.value.code == "producer_bundle_preflight_batch_missing"


def test_authority_drift_and_prefix_drift_fail_closed(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = _workspace(tmp_path)
    drifted = build_producer_bundle_publication_journal(
        journal_id=journal.journal_id, run_id=journal.run_id, parent_task_id=journal.parent_task_id,
        task_id=journal.task_id, admission_sha256=journal.admission_sha256,
        archive_prefix_sha256=journal.archive_prefix_sha256, base_archive_sha256=journal.base_archive_sha256,
        base_state_sha256=journal.base_state_sha256, contract_sha256=journal.contract_sha256,
        evaluator_kind=journal.evaluator_kind, evaluator_fingerprint=_d("f"),
        runner_fingerprint=journal.runner_fingerprint, dependency_sha256=journal.dependency_sha256,
        environment_sha256=journal.environment_sha256, budget_sha256=journal.budget_sha256,
        strategy=journal.strategy, population_config_sha256=journal.population_config_sha256,
        num_islands=journal.num_islands, candidates=journal.candidates,
    )
    with pytest.raises(ProducerBundlePreflightError) as caught:
        preflight_producer_bundle_publication(
            workspace, plan, drifted, budget_sha256=drifted.budget_sha256,
        )
    assert caught.value.code == "producer_bundle_preflight_authority_mismatch"


def test_success_is_bounded_and_zero_write(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = _workspace(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): (path.lstat().st_ino, path.read_bytes() if path.is_file() else None)
        for path in tmp_path.rglob("*")
    }
    receipt = preflight_producer_bundle_publication(
        workspace, plan, journal, budget_sha256=journal.budget_sha256,
    )
    assert receipt.plan_sha256 == plan.digest()
    assert receipt.archive_prefix_sha256 == journal.archive_prefix_sha256
    assert receipt.workspace_relative == "evolution/producer-batches/journal-1"
    after = {
        path.relative_to(tmp_path).as_posix(): (path.lstat().st_ino, path.read_bytes() if path.is_file() else None)
        for path in tmp_path.rglob("*")
    }
    assert after == before


def test_plan_candidate_mapping_and_receipt_digest_are_strict(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = _workspace(tmp_path)
    wrong = build_producer_bundle_publication_journal(
        journal_id=journal.journal_id, run_id=journal.run_id, parent_task_id=journal.parent_task_id,
        task_id=journal.task_id, admission_sha256=journal.admission_sha256,
        archive_prefix_sha256=journal.archive_prefix_sha256, base_archive_sha256=journal.base_archive_sha256,
        base_state_sha256=journal.base_state_sha256, contract_sha256=journal.contract_sha256,
        evaluator_kind=journal.evaluator_kind, evaluator_fingerprint=journal.evaluator_fingerprint,
        runner_fingerprint=journal.runner_fingerprint, dependency_sha256=journal.dependency_sha256,
        environment_sha256=journal.environment_sha256, budget_sha256=journal.budget_sha256,
        strategy=journal.strategy, population_config_sha256=journal.population_config_sha256,
        num_islands=journal.num_islands,
        candidates=(ProducerBundlePublicationCandidate(
            candidate_id="candidate-foreign", bundle_id="bundle-foreign", bundle_sha256=_d("a"),
            parent_id=None, generation=0, iteration=0, island_id=0, preparation_receipt_sha256=_d("7"),
        ),),
    )
    with pytest.raises(ProducerBundlePreflightError) as caught:
        preflight_producer_bundle_publication(workspace, plan, wrong)
    assert caught.value.code == "producer_bundle_preflight_plan_candidates_mismatch"


def test_receipt_parser_rejects_missing_self_digest(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    workspace = _workspace(tmp_path)
    receipt = preflight_producer_bundle_publication(workspace, plan, journal)
    payload = receipt.to_dict()
    payload["receipt_sha256"] = None
    with pytest.raises(ProducerBundlePreflightError) as caught:
        parse_producer_bundle_preflight_receipt(payload)
    assert caught.value.code == "producer_bundle_preflight_receipt_digest_mismatch"
