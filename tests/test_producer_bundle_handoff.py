from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_bundle import CandidateBundleError
from lunar_evolution.producer_bundle_handoff import (
    PRODUCER_BUNDLE_CONTRACT_MISMATCH,
    PRODUCER_BUNDLE_ENTRYPOINT_INVALID,
    PRODUCER_BUNDLE_ID_DUPLICATE,
    PRODUCER_BUNDLE_IDENTITY_MISMATCH,
    PRODUCER_BUNDLE_KIND_UNSUPPORTED,
    PRODUCER_BUNDLE_MATERIALS_EMPTY,
    PRODUCER_BUNDLE_PATH_DUPLICATE,
    PRODUCER_BUNDLE_PATH_REUSED,
    PRODUCER_BUNDLE_PATH_UNDECLARED,
    PRODUCER_BUNDLE_STATUS_INVALID,
    BundleGroup,
    ProducerBundleHandoffError,
    prepare_producer_bundle_manifest,
)

PRODUCER = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "producer-bundle",
            "problem_type": "routing",
            "statement": "route",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
            "decision_variables": ["route"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["valid"],
            "deliverables": ["program"],
            "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
        }
    )


def _envelope(root: Path, contract: AlgorithmProblemContract) -> dict[str, object]:
    materials = []
    for path, source in (("pkg/main.py", "print(1)\n"), ("pkg/helper.py", "VALUE = 1\n")):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        payload = target.read_bytes()
        materials.append(
            {
                "kind": "candidate_source",
                "path": path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schema_version": "1",
        "producer_id": "producer",
        "producer_fingerprint": PRODUCER,
        "status": "completed",
        "contract_sha256": contract.digest(),
        "budget": {"attempts": 1},
        "materials": materials,
    }


def test_prepare_verifies_explicit_group_without_writing(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = prepare_producer_bundle_manifest(
        tmp_path,
        envelope,
        [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        contract,
        PRODUCER,
        "producer",
    )

    assert len(result) == 1
    assert result[0].bundle_id == "bundle-1"
    assert result[0].entrypoint == "pkg/main.py"
    assert result[0].material_paths == ("pkg/helper.py", "pkg/main.py")
    assert result[0].file_count == 2
    assert result[0].total_bytes == len(b"print(1)\n") + len(b"VALUE = 1\n")
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before


def test_prepare_reuses_candidate_bundle_fixed_source_errors(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    (tmp_path / "pkg/helper.py").write_text("changed\n", encoding="utf-8")

    with pytest.raises(CandidateBundleError) as caught:
        prepare_producer_bundle_manifest(
            tmp_path,
            envelope,
            [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            contract,
            PRODUCER,
        )
    assert caught.value.code == "candidate_bundle_source_changed"


def test_prepare_rejects_material_not_declared_by_envelope(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(
            tmp_path,
            envelope,
            [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "missing.py"))],
            contract,
            PRODUCER,
        )
    assert caught.value.code == PRODUCER_BUNDLE_PATH_UNDECLARED


def test_prepare_rejects_duplicate_and_cross_group_paths(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(
            tmp_path,
            envelope,
            [
                BundleGroup("first", "pkg/main.py", ("pkg/main.py",)),
                BundleGroup("first", "pkg/helper.py", ("pkg/helper.py",)),
            ],
            contract,
            PRODUCER,
        )
    assert caught.value.code == PRODUCER_BUNDLE_ID_DUPLICATE

    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(
            tmp_path,
            envelope,
            [
                BundleGroup("first", "pkg/main.py", ("pkg/main.py",)),
                BundleGroup("second", "pkg/helper.py", ("pkg/main.py", "pkg/helper.py")),
            ],
            contract,
            PRODUCER,
        )
    assert caught.value.code == PRODUCER_BUNDLE_PATH_REUSED


def test_prepare_checks_contract_identity_status_and_material_kind(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    group = [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py",))]

    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(tmp_path, envelope, group, contract, "c" * 64)
    assert caught.value.code == PRODUCER_BUNDLE_IDENTITY_MISMATCH

    altered = dict(envelope)
    altered["contract_sha256"] = "c" * 64
    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(tmp_path, altered, group, contract, PRODUCER)
    assert caught.value.code == PRODUCER_BUNDLE_CONTRACT_MISMATCH

    altered = dict(envelope)
    altered["status"] = "failed"
    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(tmp_path, altered, group, contract, PRODUCER)
    assert caught.value.code == PRODUCER_BUNDLE_STATUS_INVALID

    altered = dict(envelope)
    altered["materials"] = [dict(altered["materials"][0], kind="log")]  # type: ignore[index]
    with pytest.raises(ProducerBundleHandoffError) as caught:
        prepare_producer_bundle_manifest(tmp_path, altered, group, contract, PRODUCER)
    assert caught.value.code == PRODUCER_BUNDLE_KIND_UNSUPPORTED


def test_ungrouped_auxiliary_material_is_ignored(tmp_path: Path) -> None:
    contract = _contract()
    envelope = _envelope(tmp_path, contract)
    auxiliary = tmp_path / "producer.log"
    auxiliary.write_text("producer evidence\n", encoding="utf-8")
    payload = auxiliary.read_bytes()
    envelope["materials"].append(
        {
            "kind": "log",
            "path": "producer.log",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )

    result = prepare_producer_bundle_manifest(
        tmp_path,
        envelope,
        [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        contract,
        PRODUCER,
    )

    assert result[0].material_paths == ("pkg/helper.py", "pkg/main.py")


def test_group_boundaries_fail_closed() -> None:
    with pytest.raises(ProducerBundleHandoffError) as caught:
        BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/main.py"))
    assert caught.value.code == PRODUCER_BUNDLE_PATH_DUPLICATE

    with pytest.raises(ProducerBundleHandoffError) as caught:
        BundleGroup("bundle-1", "pkg/other.py", ("pkg/main.py",))
    assert caught.value.code == PRODUCER_BUNDLE_ENTRYPOINT_INVALID

    with pytest.raises(ProducerBundleHandoffError) as caught:
        BundleGroup("bundle-1", "pkg/main.py", ())
    assert caught.value.code == PRODUCER_BUNDLE_MATERIALS_EMPTY
