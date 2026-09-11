from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import MAX_SOURCE_BYTES
from famou.openevolve_handoff import (
    CANDIDATE_ENCODING_INVALID,
    CANDIDATE_PATH_UNSAFE,
    CANDIDATE_TOO_LARGE,
    EVALUATOR_FINGERPRINT_REQUIRED,
    EXTERNAL_ROOT_UNSAFE,
    MAX_OPENEVOLVE_RESULT_BYTES,
    PRODUCER_FINGERPRINT_REQUIRED,
    RESULT_ENCODING_INVALID,
    RESULT_JSON_INVALID,
    RESULT_PATH_UNSAFE,
    RESULT_SCHEMA_INVALID,
    RESULT_TOO_LARGE,
    OpenEvolveHandoffError,
    admit_openevolve_result,
    declared_protocol_environment_sha256,
    source_only_dependency_sha256,
)

EVALUATOR_SHA = "a" * 64
PRODUCER_SHA = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "openevolve-handoff",
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}
            ],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {
                "strategy": "openevolve",
                "max_rounds": 2,
                "stagnation_rounds": 1,
            },
        }
    )


def _local_report(score: float = 0.75) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "local-exact-fixture",
            "validity": 1,
            "quality": score,
            "combined_score": score,
            "detailed_scores": {
                "quality": {"value": score, "direction": "maximize"}
            },
            "error_info": [],
        }
    )


def _write_result(
    root: Path,
    *,
    candidate_path: str = "candidate.py",
    evaluation: object = ...,
    result_name: str = "result.json",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"candidate_path": candidate_path}
    if evaluation is not ...:
        payload["evaluation"] = evaluation
    result_path = root / result_name
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    return result_path


def _admit(
    root: Path,
    *,
    result_path: str | os.PathLike[str] = "result.json",
    evaluator_fingerprint: object = EVALUATOR_SHA,
    producer_fingerprint: object = PRODUCER_SHA,
):
    return admit_openevolve_result(
        root,
        _contract(),
        lambda path, contract: _local_report(),
        result_path=result_path,
        evaluator_fingerprint=evaluator_fingerprint,  # type: ignore[arg-type]
        producer_fingerprint=producer_fingerprint,  # type: ignore[arg-type]
        producer_run_id="run-7",
        lineage=("parent-2",),
        staging_root=root.parent / "private-staging",
        num_islands=2,
    )


def test_result_is_admitted_with_stable_identity_and_only_local_score_authority(
    tmp_path: Path,
) -> None:
    secret = "sk-external-secret-1234567890"
    source = "def solve():\n    return 42\n"
    first_root = tmp_path / "first"
    first_root.mkdir()
    (first_root / "candidate.py").write_text(source, encoding="utf-8")
    _write_result(
        first_root,
        evaluation={
            "combined_score": 999,
            "stderr": f"producer failed with {secret}",
        },
    )
    seen: list[Path] = []

    def evaluator(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        assert contract.digest() == _contract().digest()
        assert path != first_root / "candidate.py"
        assert path.read_text(encoding="utf-8") == source
        seen.append(path)
        return _local_report(0.75)

    admitted = admit_openevolve_result(
        first_root,
        _contract(),
        evaluator,
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_fingerprint=PRODUCER_SHA,
        producer_run_id="run-7",
        lineage=("parent-2",),
        staging_root=tmp_path / "private-staging",
        num_islands=2,
    )

    assert len(seen) == 1
    assert not seen[0].exists()
    assert admitted.candidate_id.startswith("seed-")
    assert admitted.evaluation.evaluator_id == "local-exact-fixture"
    assert admitted.evaluation.combined_score == 0.75
    assert admitted.receipt.combined_score == 0.75
    assert admitted.receipt.evaluator_kind == "exact_harness"
    assert admitted.provenance.origin_kind == "external"
    assert admitted.provenance.material_refs == ()
    assert admitted.provenance.external_evidence["present"] is True
    assert admitted.provenance.external_evidence["score_present"] is True
    assert len(admitted.provenance.external_evidence["payload_sha256"]) == 64
    assert admitted.island_id in {0, 1}

    handoff = admitted.draft.metadata["seed_handoff"]
    seed_metadata = admitted.draft.metadata["seed_metadata"]
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert handoff["dependency_sha256"] == source_only_dependency_sha256(source_sha256)
    assert handoff["environment_sha256"] == declared_protocol_environment_sha256()
    assert seed_metadata["present"] is True
    assert seed_metadata["score_present"] is False
    assert len(seed_metadata["payload_sha256"]) == 64

    persisted_admission = json.dumps(
        {
            "draft": admitted.draft.metadata,
            "provenance": admitted.provenance.to_dict(),
            "receipt": admitted.receipt.to_dict(),
            "evaluation": admitted.evaluation.to_dict(),
        },
        sort_keys=True,
    )
    assert "999" not in persisted_admission
    assert secret not in persisted_admission

    # Producer configuration and external evidence are provenance.  Changing both cannot change
    # the Lunar seed identity when source, contract, evaluator, and explicit lineage are identical.
    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "candidate.py").write_text(source, encoding="utf-8")
    nested_result = _write_result(
        second_root,
        evaluation={"combined_score": -12345},
        result_name="out/result.json",
    )
    second = admit_openevolve_result(
        second_root,
        _contract(),
        lambda path, contract: _local_report(0.75),
        result_path=nested_result,
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_fingerprint="c" * 64,
        producer_run_id="different-run",
        lineage=("parent-2",),
    )
    assert second.candidate_id == admitted.candidate_id


def test_absent_external_evaluation_has_an_explicit_digest_free_summary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 42\n", encoding="utf-8")
    _write_result(root)

    admitted = _admit(root)

    assert admitted.provenance.external_evidence == {
        "present": False,
        "score_present": False,
        "payload_sha256": None,
    }
    assert admitted.draft.metadata["seed_metadata"] == {
        "present": True,
        "score_present": False,
        "payload_sha256": admitted.draft.metadata["seed_metadata"]["payload_sha256"],
    }
    assert len(admitted.draft.metadata["seed_metadata"]["payload_sha256"]) == 64


@pytest.mark.parametrize("candidate_path", ["../outside.py", "/tmp/outside.py", "a/../b.py"])
def test_candidate_path_escape_is_rejected(tmp_path: Path, candidate_path: str) -> None:
    root = tmp_path / "external"
    root.mkdir()
    _write_result(root, candidate_path=candidate_path)

    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)

    assert caught.value.code == CANDIDATE_PATH_UNSAFE


def test_result_path_must_be_confined_and_symlinks_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 42\n", encoding="utf-8")
    outside_result = _write_result(tmp_path / "outside")

    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root, result_path=outside_result)
    assert caught.value.code == RESULT_PATH_UNSAFE

    real_result = _write_result(root, result_name="real-result.json")
    (root / "result.json").symlink_to(real_result.name)
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)
    assert caught.value.code == RESULT_PATH_UNSAFE

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(linked_root, result_path="real-result.json")
    assert caught.value.code == EXTERNAL_ROOT_UNSAFE


def test_candidate_symlink_is_rejected_without_calling_local_evaluator(tmp_path: Path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n", encoding="utf-8")
    (root / "candidate.py").symlink_to(outside)
    _write_result(root)
    called = False

    def evaluator(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        nonlocal called
        called = True
        return _local_report()

    with pytest.raises(OpenEvolveHandoffError) as caught:
        admit_openevolve_result(
            root,
            _contract(),
            evaluator,
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_fingerprint=PRODUCER_SHA,
        )

    assert caught.value.code == CANDIDATE_PATH_UNSAFE
    assert called is False


@pytest.mark.parametrize(
    ("evaluator_fingerprint", "producer_fingerprint", "expected"),
    [
        ("", PRODUCER_SHA, EVALUATOR_FINGERPRINT_REQUIRED),
        (None, PRODUCER_SHA, EVALUATOR_FINGERPRINT_REQUIRED),
        (EVALUATOR_SHA, "", PRODUCER_FINGERPRINT_REQUIRED),
        (EVALUATOR_SHA, "A" * 64, PRODUCER_FINGERPRINT_REQUIRED),
    ],
)
def test_pinned_evaluator_and_producer_fingerprints_are_required(
    tmp_path: Path,
    evaluator_fingerprint: object,
    producer_fingerprint: object,
    expected: str,
) -> None:
    root = tmp_path / "external"
    root.mkdir()

    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(
            root,
            evaluator_fingerprint=evaluator_fingerprint,
            producer_fingerprint=producer_fingerprint,
        )

    assert caught.value.code == expected


def test_result_and_candidate_are_bounded_regular_utf8_files(tmp_path: Path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 42\n", encoding="utf-8")
    result = root / "result.json"

    result.write_bytes(b"x" * (MAX_OPENEVOLVE_RESULT_BYTES + 1))
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)
    assert caught.value.code == RESULT_TOO_LARGE

    result.write_bytes(b"\xff")
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)
    assert caught.value.code == RESULT_ENCODING_INVALID

    _write_result(root)
    (root / "candidate.py").write_bytes(b"\xff")
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)
    assert caught.value.code == CANDIDATE_ENCODING_INVALID

    (root / "candidate.py").write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)
    assert caught.value.code == CANDIDATE_TOO_LARGE


@pytest.mark.parametrize(
    "raw_result",
    [
        '{"candidate_path":"candidate.py","unknown":true}',
        '{"candidate_path":"candidate.py","candidate_path":"other.py"}',
        '{"candidate_path":"candidate.py","evaluation":null}',
        '[]',
    ],
)
def test_result_uses_a_fixed_duplicate_free_schema(tmp_path: Path, raw_result: str) -> None:
    root = tmp_path / "external"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 42\n", encoding="utf-8")
    (root / "result.json").write_text(raw_result, encoding="utf-8")

    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)

    assert caught.value.code in {RESULT_SCHEMA_INVALID, "result_json_invalid"}


@pytest.mark.parametrize(
    "raw_result",
    [
        b'{"candidate_path":"\\ud800"}',
        b'{"candidate_path":"line\\nbreak.py"}',
        (
            b'{"candidate_path":"candidate.py","evaluation":'
            + b"[" * 10_000
            + b"0"
            + b"]" * 10_000
            + b"}"
        ),
        b'{"candidate_path":"candidate.py","evaluation":{"note":"line\\nbreak"}}',
    ],
)
def test_surrogates_controls_and_deep_json_fail_with_fixed_adapter_codes(
    tmp_path: Path,
    raw_result: bytes,
) -> None:
    root = tmp_path / "external"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 42\n", encoding="utf-8")
    (root / "result.json").write_bytes(raw_result)

    with pytest.raises(OpenEvolveHandoffError) as caught:
        _admit(root)

    assert caught.value.code in {
        CANDIDATE_PATH_UNSAFE,
        RESULT_JSON_INVALID,
        RESULT_SCHEMA_INVALID,
    }
