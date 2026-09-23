from __future__ import annotations

from pathlib import Path

import pytest
from test_bundle_population import build_context
from test_producer_bundle_staging import fixture as publication_fixture

from lunar_evolution import (
    ProducerBundleEvaluationReceipt,
    ProducerBundleExecutionReceipt,
    ProducerBundleReceiptError,
    build_producer_bundle_evaluation_receipt,
    build_producer_bundle_execution_receipt,
    build_producer_bundle_publication_artifact,
)
from lunar_evolution.evolution import CandidateArchive, PopulationStrategy
from lunar_evolution.producer_bundle_staging import (
    ProducerBundlePublicationArtifact,
    ProducerBundlePublicationStagingError,
)


def digest(letter: str) -> str:
    return letter * 64


def report() -> dict[str, object]:
    return {
        "schema_version": "1", "evaluator_id": "fixture", "validity": 1,
        "quality": 1.0, "combined_score": 1.0, "detailed_scores": {}, "error_info": [],
    }


def test_receipts_round_trip_and_bind_canonical_projection() -> None:
    execution = ProducerBundleExecutionReceipt(
        "candidate-1", digest("a"), digest("b"), digest("c"), digest("d"),
        digest("e"), digest("f"), digest("0"), digest("1"),
    )
    evaluation = ProducerBundleEvaluationReceipt(
        "candidate-1", digest("a"), digest("b"), digest("c"), digest("d"), digest("e"),
        {"bundle_sha256": digest("a")}, report(), True, True,
    )
    assert ProducerBundleExecutionReceipt.from_dict(execution.to_dict()) == execution
    assert ProducerBundleEvaluationReceipt.from_dict(evaluation.to_dict()) == evaluation
    tampered = execution.to_dict()
    tampered["cleanup_status"] = "unknown"
    with pytest.raises(ProducerBundleReceiptError):
        ProducerBundleExecutionReceipt.from_dict(tampered)


def test_evaluation_receipt_detaches_nested_report_and_binding() -> None:
    binding = {"runner": {"fingerprint": digest("a")}}
    evaluation_report = report()
    evaluation = ProducerBundleEvaluationReceipt(
        "candidate-1", digest("a"), digest("b"), digest("c"), digest("d"), digest("e"),
        binding, evaluation_report, True, True,
    )
    binding["runner"]["fingerprint"] = digest("f")
    evaluation_report["detailed_scores"]["mutated"] = 1
    assert evaluation.binding["runner"]["fingerprint"] == digest("a")
    assert evaluation.report["detailed_scores"] == {}


def test_pipeline_evidence_projects_to_publication_artifact_and_sidecars(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    # The pipeline's default detached projection deliberately has unknown cleanup evidence.
    context.bundle_pipeline.set_process_observer(lambda pid, pgid: None, lambda pid, pgid: None)
    assert PopulationStrategy(context).run().status == "completed"
    archive = CandidateArchive(context.workspace)
    candidate = archive.records()[0]

    execution = build_producer_bundle_execution_receipt(context.workspace, candidate)
    evaluation = build_producer_bundle_evaluation_receipt(context.workspace, candidate)
    artifact = build_producer_bundle_publication_artifact(archive, candidate)
    assert artifact.execution_receipt_sha256 == execution.digest()
    assert artifact.evaluation_receipt_sha256 == evaluation.digest()
    assert artifact.execution_receipt == execution.to_dict()
    assert artifact.evaluation_receipt == evaluation.to_dict()

    # Feature 153 accepts the extra evidence sidecars while preserving native record/receipt
    # bytes.  A minimal staged batch fixture is unnecessary: the artifact constructor itself
    # checks canonical receipt hashes and reserved sidecar names.
    assert artifact.receipt["receipt_sha256"] == candidate.receipt_sha256
    with pytest.raises(ProducerBundlePublicationStagingError):
        ProducerBundlePublicationArtifact(
            artifact.candidate_id, artifact.source_files, artifact.record, artifact.receipt,
            "0" * 64, artifact.evaluation_receipt_sha256,
            execution_receipt=artifact.execution_receipt,
        )


def test_pipeline_receipt_projection_refuses_unknown_cleanup(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    def unknown_release(pid, pgid):
        raise RuntimeError("fixture release is unobserved")
    strategy = PopulationStrategy(context)
    context.bundle_pipeline.set_process_observer(lambda pid, pgid: None, unknown_release)
    assert strategy.run().status == "completed"
    candidate = CandidateArchive(context.workspace).records()[0]
    with pytest.raises(ProducerBundleReceiptError):
        build_producer_bundle_execution_receipt(context.workspace, candidate)


def test_publication_stages_native_nested_sidecars(tmp_path: Path) -> None:
    from lunar_evolution.producer_bundle_staging import (
        commit_producer_bundle_publication,
        stage_producer_bundle_publication,
    )

    workspace, journal, preflight, artifact = publication_fixture(tmp_path)
    artifact = ProducerBundlePublicationArtifact(
        artifact.candidate_id,
        {"solve/main.py": "pass\n", "solve/helper.py": "VALUE = 1\n"},
        {"candidate_id": artifact.candidate_id, "code_path": "evolution/candidates/candidate-1/solve/main.py"},
        artifact.receipt,
        artifact.execution_receipt_sha256,
        artifact.evaluation_receipt_sha256,
    )
    stage_producer_bundle_publication(
        workspace, journal, preflight, (artifact,),
        state_after={"strategy": "population"},
    )
    nested_record = workspace / "evolution/producer-batches/journal-1/stage/candidates/candidate-1/solve/record.json"
    assert nested_record.is_file()
    staged = __import__("lunar_evolution").parse_producer_bundle_publication_journal(
        workspace / "evolution/producer-batches/journal-1/journal.json"
    )
    commit_producer_bundle_publication(workspace, staged)
    assert (workspace / "evolution/candidates/candidate-1/solve/receipt.json").is_file()
