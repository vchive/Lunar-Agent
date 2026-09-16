"""Prelaunch bindings and retained evidence at native archive publication failures."""

from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest
from test_bundle_population import _files, build_context, draft_for_score

import famou.bundle_evolution as bundles
from famou import evolution
from famou.candidate_evaluation import inspect_candidate_evaluation
from famou.evolution import CandidateArchive, CandidateReceipt, EvolutionError, PopulationStrategy


def _persist(strategy, score=3):
    return strategy._persist(
        draft_for_score(score), iteration=0, generation=0, parent=None, island_id=0,
    )


def _stop_launch(monkeypatch):
    calls = []

    def launch(*args, **kwargs):
        calls.append(kwargs)
        raise EvolutionError("unexpected_candidate_launch")

    monkeypatch.setattr(bundles, "run_candidate_execution_recorded", launch)
    return calls


def test_changed_harness_after_strategy_construction_fails_before_source_or_launch(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    context.bundle_pipeline.harness_path.write_text("raise SystemExit(99)\n")
    calls = _stop_launch(monkeypatch)

    with pytest.raises(evolution._InitialCandidateFailure, match="candidate_failed"):
        _persist(strategy)

    assert not calls
    assert not strategy.archive.candidates_root.exists()
    assert not (strategy.archive.root / "bundle-attempts").exists()


def test_nested_contract_change_after_strategy_construction_fails_before_launch(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    original_digest = strategy.integrity_authority.contract_sha256
    context.contract.inputs[0].fields["value"] = "changed meaning after authority was fixed"
    assert context.contract.digest() != original_digest
    calls = _stop_launch(monkeypatch)

    with pytest.raises(evolution._InitialCandidateFailure, match="candidate_failed"):
        _persist(strategy)

    assert not calls
    assert not strategy.archive.candidates_root.exists()
    assert not (strategy.archive.root / "bundle-attempts").exists()


@pytest.mark.parametrize("record", ["plan", "admission", "completion"])
def test_saved_execution_binding_drift_rejects_resume_without_relaunch(tmp_path, monkeypatch, record):
    context = build_context(tmp_path)
    assert PopulationStrategy(context).run().status == "completed"
    candidate = CandidateArchive(context.workspace).best()
    root = context.workspace / candidate.bundle_evidence["run_root"]
    target = root / ("attempt/completed.json" if record == "completion" else record + ".json")
    value = json.loads(target.read_bytes())
    if record == "plan":
        value["timeout_seconds"] += 1
    elif record == "admission":
        value["dependency_sha256"] = "e" * 64
    else:
        value["result"]["sha256"] = "f" * 64
    target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    before = _files(context.workspace)
    launches = _stop_launch(monkeypatch)

    def reject_generation(request):
        pytest.fail("changed saved bindings must be rejected before generation")

    with pytest.raises(EvolutionError):
        PopulationStrategy(replace(context, generate=reject_generation)).resume()

    assert not launches
    assert _files(context.workspace) == before


def test_failed_record_publication_keeps_completed_attempt_and_retry_uses_fresh_root(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    original_write = strategy.archive._atomic_write_bytes

    def fail_record(path, content, **kwargs):
        if path.name == "record.json":
            raise EvolutionError("fixture_record_publication_failed")
        original_write(path, content, **kwargs)

    monkeypatch.setattr(strategy.archive, "_atomic_write_bytes", fail_record)
    with pytest.raises(evolution._InitialCandidateFailure, match="candidate_failed"):
        _persist(strategy)

    assert strategy.archive.records() == []
    assert not (strategy.archive.candidates_root / "candidate-0001").exists()
    attempts = list((strategy.archive.root / "bundle-attempts").iterdir())
    assert len(attempts) == 1
    retained = attempts[0]
    assert (retained / "attempt/completed.json").is_file()
    evaluation = next((retained / "evaluations").iterdir())
    assert inspect_candidate_evaluation(evaluation).report.combined_score == 3
    assert [path.read_text() for path in retained.rglob("count")] == ["x"]
    before = _files(retained)

    monkeypatch.setattr(strategy.archive, "_atomic_write_bytes", original_write)
    candidate = _persist(strategy, 4)

    assert candidate.candidate_id == "candidate-0001"
    assert candidate.evaluation.combined_score == 4
    assert context.workspace / candidate.bundle_evidence["run_root"] != retained
    assert len(strategy.archive.records()) == 1
    assert _files(retained) == before
    assert len(list((strategy.archive.root / "bundle-attempts").rglob("count"))) == 2


def test_unknown_archive_publication_retains_bundle_sidecars_and_scored_attempt(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    archive_path = strategy.archive.archive_path
    original_fsync = os.fsync
    archive_sync_calls = 0

    def fail_archive_and_rollback_sync(descriptor):
        nonlocal archive_sync_calls
        try:
            opened = os.fstat(descriptor)
            current = archive_path.stat()
        except OSError:
            return original_fsync(descriptor)
        if (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino):
            archive_sync_calls += 1
            if archive_sync_calls <= 2:
                raise OSError("fixture archive durability failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_archive_and_rollback_sync)
    with pytest.raises(evolution._CandidateArchivePublicationUnknown):
        _persist(strategy)

    assert archive_sync_calls == 2
    assert archive_path.read_bytes() == b""
    source_root = strategy.archive.candidates_root / "candidate-0001"
    assert (source_root / "solve/main.py").is_file()
    assert (source_root / "solve/helper.py").is_file()
    assert (source_root / "bundle-manifest.json").is_file()
    assert (source_root / "solve/record.json").is_file()
    receipt = CandidateReceipt.from_dict(json.loads((source_root / "solve/receipt.json").read_bytes()))
    assert receipt.schema_version == "2"
    run = context.workspace / receipt.bundle_evidence["run_root"]
    assert (run / "attempt/completed.json").is_file()
    evaluation = inspect_candidate_evaluation(
        context.workspace / receipt.bundle_evidence["evaluation_path"],
        expected_evaluation_sha256=receipt.bundle_evidence["evaluation_sha256"],
    )
    assert evaluation.report.combined_score == 3
    assert [path.read_text() for path in run.rglob("count")] == ["x"]
    assert not strategy.archive.offspring_outcomes()
