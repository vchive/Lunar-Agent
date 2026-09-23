from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution.evolution import CandidateArchive, EvolutionError


def _marker(workspace: Path) -> Path:
    path = workspace / "evolution" / "producer-publication.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"protocol": "lunar-producer-bundle-publication-v1"}), encoding="utf-8")
    return path


def test_unresolved_producer_publication_blocks_archive_constructor(tmp_path: Path) -> None:
    _marker(tmp_path)
    with pytest.raises(EvolutionError, match="producer_bundle_publication_recovery_required"):
        CandidateArchive(tmp_path, requested_strategy="population", read_only=True)


def test_marker_created_after_constructor_blocks_reads_and_writes(tmp_path: Path) -> None:
    archive = CandidateArchive(tmp_path, requested_strategy="population")
    _marker(tmp_path)
    with pytest.raises(EvolutionError, match="producer_bundle_publication_recovery_required"):
        archive.records()
    with pytest.raises(EvolutionError, match="producer_bundle_publication_recovery_required"):
        archive.read_state()
    with pytest.raises(EvolutionError, match="producer_bundle_publication_recovery_required"):
        archive.write_state({"strategy": "population", "config": {"strategy": "population"}})


def test_missing_marker_does_not_change_legacy_archive_behavior(tmp_path: Path) -> None:
    archive = CandidateArchive(tmp_path, requested_strategy="population")
    assert archive.records() == []
    assert archive.read_state() == {}
