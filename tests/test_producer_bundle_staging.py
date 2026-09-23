from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.producer_bundle_preflight import ProducerBundlePreflightReceipt
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
)
from lunar_evolution.producer_bundle_staging import (
    ProducerBundlePublicationArtifact,
    ProducerBundlePublicationStagingError,
    commit_producer_bundle_publication,
    stage_producer_bundle_publication,
)


def d(letter: str) -> str:
    return letter * 64


def fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    batch = workspace / "evolution" / "producer-batches" / "journal-1"
    batch.mkdir(parents=True)
    (workspace / "evolution" / "candidates").mkdir()
    (workspace / "evolution" / "archive.jsonl").write_bytes(b"")
    state = {"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": []}}
    state_bytes = json.dumps(state, sort_keys=True).encode()
    (workspace / "evolution" / "state.json").write_bytes(state_bytes)
    candidate = ProducerBundlePublicationCandidate(
        "candidate-1", "bundle-1", d("a"), None, 0, 0, 0, d("b"),
    )
    journal = build_producer_bundle_publication_journal(
        journal_id="journal-1", run_id="run-1", parent_task_id="parent-1", task_id="task-1",
        admission_sha256=d("c"), archive_prefix_sha256=d("d"),
        base_archive_sha256=hashlib.sha256(b"").hexdigest(),
        base_state_sha256=hashlib.sha256(state_bytes).hexdigest(), contract_sha256=d("0"),
        evaluator_kind="callback", evaluator_fingerprint=d("1"), runner_fingerprint=d("2"),
        dependency_sha256=d("3"), environment_sha256=d("4"), budget_sha256=d("5"),
        strategy="population", population_config_sha256=d("6"), num_islands=1,
        candidates=(candidate,),
    )
    receipt = ProducerBundlePreflightReceipt(
        journal_id="journal-1", run_id="run-1", task_id="task-1", plan_sha256=d("7"),
        archive_prefix_sha256=d("d"), base_archive_sha256=journal.base_archive_sha256,
        base_state_sha256=journal.base_state_sha256, authority_sha256=d("8"),
        candidate_ids=(candidate.candidate_id,), record_count=0,
        workspace_relative="evolution/producer-batches/journal-1",
    )
    artifact = ProducerBundlePublicationArtifact(
        candidate.candidate_id, {"main.py": "print('ok')\n"},
        {"candidate_id": candidate.candidate_id}, {"receipt_sha256": d("9")},
        execution_receipt_sha256=d("c"), evaluation_receipt_sha256=d("e"),
    )
    return workspace, journal, receipt, artifact


def test_stage_is_zero_exposure_and_commit_publishes_atomically(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    manifest = stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,),
        state_after={"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": ["candidate-1"]}},
    )
    assert manifest.status == "staged"
    assert not (workspace / "evolution" / "archive.jsonl").read_bytes()
    assert not (workspace / "evolution" / "candidates" / "candidate-1").exists()
    assert (workspace / "evolution" / "producer-publication.json").is_file()
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    final = commit_producer_bundle_publication(workspace, staged)
    assert final.state == "published"
    assert (workspace / "evolution" / "candidates" / "candidate-1" / "main.py").read_text() == "print('ok')\n"
    assert json.loads((workspace / "evolution" / "archive.jsonl").read_text()) == {
        "candidate_id": "candidate-1",
    }
    assert not (workspace / "evolution" / "producer-publication.json").exists()
    assert parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    ).state == "published"


def test_stage_rejects_missing_receipt_sequence_without_marker(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    incomplete = ProducerBundlePublicationArtifact(
        artifact.candidate_id, artifact.source_files, artifact.record, artifact.receipt,
    )
    with pytest.raises(ProducerBundlePublicationStagingError) as caught:
        stage_producer_bundle_publication(
            workspace, journal, receipt, (incomplete,), state_after={"strategy": "population"},
        )
    assert caught.value.code == "producer_bundle_publication_receipt_sequence_invalid"
    assert not (workspace / "evolution" / "producer-publication.json").exists()


def test_commit_with_tampered_stage_is_unknown_and_marker_remains(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), state_after={"strategy": "population"},
    )
    archive = workspace / "evolution" / "producer-batches" / "journal-1" / "stage" / "archive.jsonl"
    archive.write_bytes(archive.read_bytes() + b"tampered")
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    with pytest.raises(ProducerBundlePublicationStagingError):
        commit_producer_bundle_publication(workspace, staged)
    assert (workspace / "evolution" / "producer-publication.json").is_file()


def test_mixed_batch_records_rejected_without_publishing_it(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    rejected = ProducerBundlePublicationCandidate(
        "candidate-2", "bundle-2", d("2"), None, 0, 0, 0, d("3"),
    )
    journal = build_producer_bundle_publication_journal(
        **{**journal.to_dict(), "journal_sha256": None,
           "num_islands": 1, "candidates": (journal.candidates[0], rejected)},
    )
    stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), rejected_candidate_ids=("candidate-2",),
        state_after={"strategy": "population"},
    )
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    assert [item.status for item in staged.candidates] == ["admitted", "rejected"]


def test_all_rejected_batch_is_not_staged(tmp_path: Path) -> None:
    workspace, journal, receipt, _ = fixture(tmp_path)
    with pytest.raises(ProducerBundlePublicationStagingError) as caught:
        stage_producer_bundle_publication(
            workspace, journal, receipt, (), rejected_candidate_ids=("candidate-1",),
            state_after={"strategy": "population"},
        )
    assert caught.value.code == "producer_bundle_publication_no_admitted_candidates"
    assert not (workspace / "evolution" / "producer-publication.json").exists()
