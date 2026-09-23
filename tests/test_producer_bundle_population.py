"""Provider-free projection from verified producer bundles to native drafts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.producer_bundle_handoff import (
    BundleGroup,
    prepare_producer_bundle_manifest,
)
from lunar_evolution.producer_bundle_population import (
    ProducerBundlePopulationError,
    prepare_producer_bundle_drafts,
)

PRODUCER = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "producer-bundle-population",
            "problem_type": "routing",
            "statement": "route",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
            "decision_variables": ["route"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["valid"],
            "deliverables": ["program"],
            "evolution": {
                "strategy": "population",
                "max_rounds": 1,
                "stagnation_rounds": 1,
            },
        }
    )


def _verified_bundle(root: Path, *, bundle_id: str = "bundle-1", prefix: str = "pkg"):
    materials: list[dict[str, object]] = []
    for path, source in (
        (f"{prefix}/main.py", "from helper import VALUE\n"),
        (f"{prefix}/helper.py", "VALUE = 1\n"),
    ):
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
    envelope = {
        "schema_version": "1",
        "producer_id": "producer",
        "producer_fingerprint": PRODUCER,
        "status": "completed",
        "contract_sha256": _contract().digest(),
        "budget": {"attempts": 1},
        "materials": materials,
    }
    return prepare_producer_bundle_manifest(
        root,
        envelope,
        [BundleGroup(bundle_id, f"{prefix}/main.py", (f"{prefix}/main.py", f"{prefix}/helper.py"))],
        _contract(),
        PRODUCER,
        "producer",
    )[0]


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_projection_preserves_files_entrypoint_and_provenance_without_writes(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    before = _files(tmp_path)

    result = prepare_producer_bundle_drafts(tmp_path, (bundle,))

    assert len(result) == 1
    item = result[0]
    assert item.bundle_id == "bundle-1"
    assert item.entrypoint == "pkg/main.py"
    assert item.material_paths == ("pkg/helper.py", "pkg/main.py")
    assert item.draft.source == "from helper import VALUE\n"
    assert item.draft.source_files == {
        "pkg/main.py": "from helper import VALUE\n",
        "pkg/helper.py": "VALUE = 1\n",
    }
    assert item.draft.metadata == {
        "producer_bundle": {
            "bundle_id": "bundle-1",
            "bundle_sha256": bundle.bundle_sha256,
            "producer_fingerprint": PRODUCER,
            "producer_id": "producer",
            "envelope_sha256": bundle.envelope_sha256,
        }
    }
    assert _files(tmp_path) == before


def test_projection_preserves_explicit_bundle_order(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    second = _verified_bundle(tmp_path, bundle_id="bundle-2", prefix="other")

    result = prepare_producer_bundle_drafts(tmp_path, [second, bundle])

    assert [item.bundle_id for item in result] == ["bundle-2", "bundle-1"]


def test_projection_rejects_duplicate_ids_and_cross_bundle_path_reuse(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)

    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path, [bundle, bundle])
    assert caught.value.code == "producer_bundle_population_id_duplicate"

    reused = replace(bundle, bundle_id="bundle-2")
    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path, [bundle, reused])
    assert caught.value.code == "producer_bundle_population_path_reused"


def test_projection_rejects_tampered_sources_and_invalid_root(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    (tmp_path / "pkg" / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path, (bundle,))
    assert caught.value.code == "producer_bundle_population_source_changed"

    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path / "missing", (bundle,))
    assert caught.value.code == "producer_bundle_population_root_invalid"

    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(alias, (bundle,))
    assert caught.value.code == "producer_bundle_population_root_invalid"


def test_projection_rejects_empty_or_foreign_bundle_lists(tmp_path: Path) -> None:
    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path, [])
    assert caught.value.code == "producer_bundle_population_bundles_invalid"

    with pytest.raises(ProducerBundlePopulationError) as caught:
        prepare_producer_bundle_drafts(tmp_path, [object()])  # type: ignore[list-item]
    assert caught.value.code == "producer_bundle_population_bundle_invalid"
