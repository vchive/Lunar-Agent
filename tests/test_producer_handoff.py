from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import MAX_SOURCE_BYTES
from famou.producer_handoff import (
    MAX_PRODUCER_ENVELOPE_BYTES,
    PRODUCER_BUDGET_INVALID,
    PRODUCER_CONTRACT_MISMATCH,
    PRODUCER_ENVELOPE_ENCODING_INVALID,
    PRODUCER_ENVELOPE_JSON_INVALID,
    PRODUCER_ENVELOPE_PATH_UNSAFE,
    PRODUCER_ENVELOPE_SCHEMA_INVALID,
    PRODUCER_ENVELOPE_STATUS_INVALID,
    PRODUCER_FINGERPRINT_REQUIRED,
    PRODUCER_IDENTITY_MISMATCH,
    PRODUCER_MATERIAL_DIGEST_MISMATCH,
    PRODUCER_MATERIAL_KIND_UNSUPPORTED,
    PRODUCER_MATERIAL_NOT_REGULAR,
    PRODUCER_MATERIAL_PATH_UNSAFE,
    PRODUCER_MATERIAL_SIZE_MISMATCH,
    PRODUCER_MATERIAL_TOO_LARGE,
    PRODUCER_RESULT_PROTOCOL,
    PRODUCER_ROOT_UNSAFE,
    ProducerHandoffError,
    ProducerMaterial,
    ProducerResultEnvelope,
    admit_producer_result,
    declared_producer_environment_sha256,
    parse_producer_envelope,
    producer_bundle_dependency_sha256,
)
from famou.seed_handoff import SeedAdmissionError

EVALUATOR_SHA = "a" * 64
PRODUCER_SHA = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "shinka-envelope",
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {"strategy": "population", "max_rounds": 2, "stagnation_rounds": 1},
        }
    )


def _report(score: float, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "shinka-local-exact",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
            "error_info": [] if valid else [{"code": "invalid", "message": "private detail"}],
        }
    )


def _material(root: Path, name: str, source: str, *, evidence: object = None, lineage=()) -> dict[str, object]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    payload: dict[str, object] = {
        "kind": "candidate_source",
        "path": name,
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "lineage": list(lineage),
    }
    if evidence is not None:
        payload["external_evidence"] = evidence
    return payload


def _envelope(
    root: Path,
    contract: AlgorithmProblemContract,
    materials: list[dict[str, object]],
    *,
    status: str = "completed",
    producer_id: str = "shinka",
    producer_fingerprint: str = PRODUCER_SHA,
    producer_run_id: str | None = "shinka-run-1",
    evidence: object = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1",
        "producer_id": producer_id,
        "producer_fingerprint": producer_fingerprint,
        "producer_run_id": producer_run_id,
        "status": status,
        "contract_sha256": contract.digest(),
        "budget": {"max_iterations": 4, "max_attempts": 12, "timeout_seconds": 30},
        "materials": materials,
    }
    if evidence is not None:
        payload["external_evidence"] = evidence
    root.mkdir(parents=True, exist_ok=True)
    (root / "producer-result.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _admit(root: Path, *, evaluator=None, **kwargs):
    return admit_producer_result(
        root,
        _contract(),
        evaluator or (lambda path, contract: _report(0.75)),
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_fingerprint=PRODUCER_SHA,
        staging_root=root.parent / "staging",
        **kwargs,
    )


def test_shinka_like_envelope_round_trips_and_normalizes_external_evidence() -> None:
    contract = _contract()
    first = ProducerResultEnvelope(
        schema_version="1",
        producer_id="shinka",
        producer_fingerprint=PRODUCER_SHA,
        status="completed",
        contract_sha256=contract.digest(),
        budget={"max_iterations": 4, "max_attempts": 12},
        materials=(
            ProducerMaterial(
                "candidate_source",
                "gen_3/main.py",
                12,
                "c" * 64,
                lineage=("program-root", "program-child"),
                external_evidence={"combined_score": 9999, "correct": True, "text_feedback": "discard"},
            ),
        ),
        external_evidence={"best_combined_score": 10000},
    )
    second = ProducerResultEnvelope.from_dict(first.to_dict())

    assert second == first
    assert second.envelope_sha256 == first.envelope_sha256
    assert second.to_dict()["materials"][0]["external_evidence"]["score_present"] is True
    assert second.to_dict()["external_evidence"]["score_present"] is True
    assert PRODUCER_RESULT_PROTOCOL == "lunar-producer-result-v1"


def test_terminal_noncompleted_envelopes_round_trip_without_materials() -> None:
    contract = _contract()
    for status in ("failed", "cancelled", "unknown"):
        envelope = ProducerResultEnvelope(
            schema_version="1",
            producer_id="shinka",
            producer_fingerprint=PRODUCER_SHA,
            status=status,  # type: ignore[arg-type]
            contract_sha256=contract.digest(),
            budget={"max_iterations": 1},
            materials=(),
        )
        assert ProducerResultEnvelope.from_dict(envelope.to_dict()) == envelope
        assert parse_producer_envelope(json.dumps(envelope.to_dict())) == envelope


def test_envelope_pathlike_and_huge_budget_use_fixed_boundaries(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.py", "answer = 1\n")
    _envelope(root, contract, [material])

    result = _admit(root, envelope_path=Path("producer-result.json"))
    assert len(result.admitted) == 1

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerResultEnvelope(
            "1",
            "shinka",
            PRODUCER_SHA,
            "completed",
            contract.digest(),
            {"max_iterations": 10**1000},
            (ProducerMaterial("candidate_source", "candidate.py", 1, "c" * 64),),
        )
    assert caught.value.code == PRODUCER_BUDGET_INVALID


def test_malformed_direct_dtos_fail_with_fixed_codes() -> None:
    contract = _contract()
    with pytest.raises(ProducerHandoffError) as caught:
        ProducerResultEnvelope(
            "1",
            "shinka",
            PRODUCER_SHA,
            [],  # type: ignore[arg-type]
            contract.digest(),
            {"max_iterations": 1},
            (),
        )
    assert caught.value.code == PRODUCER_ENVELOPE_STATUS_INVALID

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerResultEnvelope(
            "1",
            "shinka",
            PRODUCER_SHA,
            "completed",
            contract.digest(),
            {"max_iterations": 1},
            None,  # type: ignore[arg-type]
        )
    assert caught.value.code == PRODUCER_ENVELOPE_SCHEMA_INVALID

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerMaterial("candidate_source", "candidate.py", 0, "c" * 64)
    assert caught.value.code == PRODUCER_MATERIAL_TOO_LARGE

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerMaterial(
            "candidate_source",
            "candidate.py",
            1,
            "c" * 64,
            lineage=None,  # type: ignore[arg-type]
        )
    assert caught.value.code == PRODUCER_ENVELOPE_SCHEMA_INVALID


def test_non_completed_envelopes_can_be_empty_but_are_not_admitted() -> None:
    envelope = ProducerResultEnvelope(
        "1",
        "shinka",
        PRODUCER_SHA,
        "unknown",
        "c" * 64,
        {"max_iterations": 1},
        (),
    )
    assert envelope.materials == ()
    assert ProducerResultEnvelope.from_dict(envelope.to_dict()) == envelope


def test_materials_are_admitted_through_one_global_seed_manifest(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    first = _material(
        root,
        "gen_1/main.py",
        "answer = 1\n",
        evidence={
            "combined_score": 999,
            "correct": True,
            "text_feedback": "discard me\nwith tab\tand prose",
        },
        lineage=("root-a",),
    )
    second = _material(
        root,
        "gen_2/main.py",
        "answer = 2\n",
        evidence={"combined_score": 998, "correct": True},
        lineage=("root-b",),
    )
    _envelope(
        root,
        contract,
        [first, second],
        evidence={"best_combined_score": 1000, "run_note": "untrusted"},
    )
    calls: list[Path] = []

    def evaluator(path: Path, supplied: AlgorithmProblemContract) -> EvaluationReport:
        assert supplied == contract
        calls.append(path)
        return _report(0.25 if path.read_text(encoding="utf-8").endswith("1\n") else 0.5)

    result = admit_producer_result(
        root,
        contract,
        evaluator,
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_fingerprint=PRODUCER_SHA,
        staging_root=tmp_path / "staging",
        num_islands=2,
    )

    assert len(result.admitted) == 2
    assert len(calls) == 2
    assert {item.island_id for item in result.admitted} == {0, 1}
    assert all(item.receipt.evaluator_kind == "exact_harness" for item in result.admitted)
    assert [item.evaluation.combined_score for item in result.admitted] == [0.25, 0.5]
    for item in result.admitted:
        evidence = item.provenance.external_evidence
        assert evidence["present"] is True
        assert evidence["score_present"] is True
        assert len(evidence["payload_sha256"]) == 64
        assert item.draft.metadata["seed_metadata"]["present"] is True
        serialized = json.dumps(item.draft.metadata, sort_keys=True)
        assert "999" not in serialized
        assert "discard me" not in serialized
        assert "with tab" not in serialized

    source_digests = [first["sha256"], second["sha256"]]
    assert result.admitted[0].receipt.dependency_sha256 == producer_bundle_dependency_sha256(
        source_digests
    )
    assert result.admitted[0].receipt.environment_sha256 == declared_producer_environment_sha256()


def test_mixed_local_evaluation_batch_returns_only_admitted_materials(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    good = _material(root, "good.py", "answer = 1\n")
    bad = _material(root, "bad.py", "answer = 2\n", evidence={"combined_score": 999})
    _envelope(root, contract, [good, bad])

    result = _admit(
        root,
        evaluator=lambda path, supplied: _report(
            1 if path.name == "good.py" else 999,
            valid=1 if path.name == "good.py" else 0,
        ),
        num_islands=2,
    )

    assert len(result.admitted) == 1
    assert result.admitted[0].draft.source == "answer = 1\n"
    assert len(result.rejected) == 1
    assert result.rejected[0].source_path == "bad.py"
    assert result.rejected[0].code == "local_evaluation_invalid"


def test_same_source_with_different_lineage_gets_distinct_seed_ids(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    first = _material(root, "a.py", "answer = 1\n", lineage=("parent-a",))
    second = _material(root, "b.py", "answer = 1\n", lineage=("parent-b",))
    _envelope(root, contract, [first, second])
    result = _admit(root)
    assert len(result.admitted) == 2
    assert len({item.candidate_id for item in result.admitted}) == 2


def test_invalid_local_evaluation_rejects_external_high_score_without_population_seed(
    tmp_path: Path,
) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "best/main.py", "answer = 42\n", evidence={"combined_score": 1e9})
    _envelope(root, contract, [material])

    with pytest.raises(SeedAdmissionError) as caught:
        _admit(root, evaluator=lambda path, supplied: _report(1e9, valid=0))

    assert caught.value.result is not None
    assert caught.value.result.admitted == ()
    assert caught.value.result.rejected[0].code == "local_evaluation_invalid"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("status", PRODUCER_ENVELOPE_STATUS_INVALID),
        ("contract_sha256", PRODUCER_CONTRACT_MISMATCH),
        ("producer_fingerprint", PRODUCER_IDENTITY_MISMATCH),
    ],
)
def test_envelope_authority_and_status_are_checked_before_local_evaluation(
    tmp_path: Path,
    field: str,
    expected: str,
) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.py", "answer = 1\n")
    payload = _envelope(root, contract, [material])
    payload[field] = "running" if field == "status" else ("d" * 64 if field == "producer_fingerprint" else "e" * 64)
    (root / "producer-result.json").write_text(json.dumps(payload), encoding="utf-8")
    called = False

    def evaluator(path, supplied):
        nonlocal called
        called = True
        return _report(1)

    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root, evaluator=evaluator)
    assert caught.value.code == expected
    assert called is False


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda payload: payload["materials"][0].update({"size": 999}), PRODUCER_MATERIAL_SIZE_MISMATCH),
        (lambda payload: payload["materials"][0].update({"sha256": "d" * 64}), PRODUCER_MATERIAL_DIGEST_MISMATCH),
        (lambda payload: payload["materials"][0].update({"kind": "metrics"}), PRODUCER_MATERIAL_KIND_UNSUPPORTED),
        (lambda payload: payload["materials"][0].update({"path": "../escape.py"}), PRODUCER_MATERIAL_PATH_UNSAFE),
    ],
)
def test_material_integrity_and_kind_fail_closed(tmp_path: Path, mutator, expected: str) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.py", "answer = 1\n")
    payload = _envelope(root, contract, [material])
    mutator(payload)
    (root / "producer-result.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == expected


def test_root_and_symlink_materials_are_rejected(tmp_path: Path) -> None:
    contract = _contract()
    real = tmp_path / "real"
    material = _material(real, "candidate.py", "answer = 1\n")
    _envelope(real, contract, [material])
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(linked)
    assert caught.value.code == PRODUCER_ROOT_UNSAFE

    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n", encoding="utf-8")
    (real / "candidate.py").unlink()
    (real / "candidate.py").symlink_to(outside)
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(real)
    assert caught.value.code == "producer_material_path_unsafe"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable on this platform")
def test_fifo_material_is_rejected_without_blocking(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.pipe", "answer = 1\n")
    _envelope(root, contract, [material])
    candidate = root / "candidate.pipe"
    candidate.unlink()
    os.mkfifo(candidate)

    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == PRODUCER_MATERIAL_NOT_REGULAR


def test_envelope_path_symlink_is_rejected_with_a_fixed_path_code(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.py", "answer = 1\n")
    _envelope(root, contract, [material])
    real_envelope = root / "producer-result.json"
    linked_envelope = root / "linked-result.json"
    linked_envelope.symlink_to(real_envelope)
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root, envelope_path="linked-result.json")
    assert caught.value.code == PRODUCER_ENVELOPE_PATH_UNSAFE


def test_envelope_bounds_and_strict_json_are_fixed_code(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "producer"
    material = _material(root, "candidate.py", "answer = 1\n")
    payload = _envelope(root, contract, [material])

    payload["unknown"] = True
    (root / "producer-result.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == PRODUCER_ENVELOPE_SCHEMA_INVALID

    (root / "producer-result.json").write_bytes(b"\xff")
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == PRODUCER_ENVELOPE_ENCODING_INVALID

    (root / "producer-result.json").write_text('{"schema_version":"1","schema_version":"1"}', encoding="utf-8")
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == PRODUCER_ENVELOPE_JSON_INVALID

    (root / "producer-result.json").write_bytes(b"x" * (MAX_PRODUCER_ENVELOPE_BYTES + 1))
    with pytest.raises(ProducerHandoffError) as caught:
        _admit(root)
    assert caught.value.code == "producer_envelope_too_large"


def test_evidence_credentials_controls_and_budget_bounds_are_rejected() -> None:
    contract = _contract()
    with pytest.raises(ProducerHandoffError) as caught:
        ProducerResultEnvelope(
            "1",
            "shinka",
            PRODUCER_SHA,
            "completed",
            contract.digest(),
            {"max_iterations": 1},
            (
                ProducerMaterial(
                    "candidate_source",
                    "candidate.py",
                    1,
                    "c" * 64,
                    external_evidence={"note": "api_key=super-secret"},
                ),
            ),
        )
    assert caught.value.code == PRODUCER_ENVELOPE_SCHEMA_INVALID

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerResultEnvelope(
            "1",
            "shinka",
            PRODUCER_SHA,
            "completed",
            contract.digest(),
            {"max_iterations": 1, "bad-key": 2},
            (ProducerMaterial("candidate_source", "candidate.py", 1, "c" * 64),),
        )
    assert caught.value.code == PRODUCER_BUDGET_INVALID

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerMaterial("candidate_source", "candidate.py", MAX_SOURCE_BYTES + 1, "c" * 64)
    assert caught.value.code == PRODUCER_MATERIAL_TOO_LARGE

    with pytest.raises(ProducerHandoffError) as caught:
        ProducerMaterial("candidate_source", "api_key=super-secret.py", 1, "c" * 64)
    assert caught.value.code == PRODUCER_MATERIAL_PATH_UNSAFE


def test_bundle_digest_is_path_free_and_bounded() -> None:
    first = producer_bundle_dependency_sha256(["a" * 64, "b" * 64])
    second = producer_bundle_dependency_sha256(["b" * 64, "a" * 64])
    assert first == second
    with pytest.raises(ProducerHandoffError):
        producer_bundle_dependency_sha256(["A" * 64])


def test_required_producer_fingerprint_is_pinned_before_reading_envelope(tmp_path: Path) -> None:
    with pytest.raises(ProducerHandoffError) as caught:
        admit_producer_result(
            tmp_path,
            _contract(),
            lambda path, contract: _report(1),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_fingerprint="short",
        )
    assert caught.value.code == PRODUCER_FINGERPRINT_REQUIRED
