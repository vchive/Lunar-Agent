"""Native delivery inspection never allocates or recovers retained archives."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_candidate_integrity import _config, _contract, _report, _run

from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import (
    CandidateArchive,
    CandidateDraft,
    EvolutionContext,
    EvolutionError,
    PopulationStrategy,
)
from lunar_evolution.runtime import MockRuntime


def _snapshot(root: Path):
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        content = (os.readlink(path) if path.is_symlink()
                   else path.read_bytes() if path.is_file() else None)
        result[path.relative_to(root).as_posix()] = (
            info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, content,
        )
    return result


def _forbidden(*args, **kwargs):
    pytest.fail("read-only inspection attempted an effect")


@pytest.mark.parametrize("read_only", [None, 0, 1, "true"])
def test_read_only_option_requires_boolean(tmp_path, read_only):
    with pytest.raises(EvolutionError, match="read_only_invalid"):
        CandidateArchive(tmp_path, read_only=read_only)


def test_missing_archive_workspace_is_never_created(tmp_path, monkeypatch):
    workspace = tmp_path / "missing" / "workspace"
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    with pytest.raises(EvolutionError, match="workspace_missing"):
        CandidateArchive(workspace, read_only=True)
    assert not workspace.parent.exists()


def test_empty_workspace_inspection_does_not_allocate_archive(tmp_path, monkeypatch):
    before = _snapshot(tmp_path)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(CandidateArchive, "_recover_seed_publication", _forbidden)
    archive = CandidateArchive(tmp_path, read_only=True)
    assert archive.records() == []
    assert archive.read_state() == {}
    assert not archive.root.exists()
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("name", [
    ".evolution-seed-stage-v1", ".evolution-seed-backup-v1",
    ".evolution-seed-stage-other", ".evolution-seed-backup-other",
])
@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_every_recovery_marker_is_retained_and_requires_recovery(tmp_path, monkeypatch, name, kind):
    marker = tmp_path / name
    if kind == "directory":
        marker.mkdir()
        (marker / "retained.json").write_bytes(b"retained evidence")
    elif kind == "file":
        marker.write_bytes(b"retained evidence")
    else:
        marker.symlink_to(tmp_path / "absent-target")
    before = _snapshot(tmp_path)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(CandidateArchive, "_recover_seed_publication", _forbidden)
    with pytest.raises(EvolutionError, match="recovery_required"):
        CandidateArchive(tmp_path, read_only=True)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("relative", ["evolution", "evolution/candidates"])
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_read_only_archive_rejects_unsafe_directories(tmp_path, relative, kind):
    target = tmp_path / relative
    target.parent.mkdir(exist_ok=True)
    if kind == "file":
        target.write_bytes(b"retained")
    else:
        target.symlink_to(tmp_path / "missing")
    before = _snapshot(tmp_path)
    with pytest.raises(EvolutionError, match="directory_invalid"):
        CandidateArchive(tmp_path, read_only=True)
    assert _snapshot(tmp_path) == before


def test_read_only_population_integrity_checks_without_callbacks_or_writes(tmp_path, monkeypatch):
    # Only callbacks build this archive; candidate source remains unevaluated data.
    expected = _run(tmp_path)

    class InertCallback:
        __call__ = staticmethod(_forbidden)
        set_observer = staticmethod(_forbidden)
        set_remaining_timeout = staticmethod(_forbidden)

    context = EvolutionContext(
        _contract(), tmp_path, InertCallback(), InertCallback(), _config(),
    )
    before = _snapshot(tmp_path)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(CandidateArchive, "_recover_seed_publication", _forbidden)
    strategy = PopulationStrategy(context, read_only=True)
    strategy.validate_ordinary_resume_integrity()
    strategy.validate_ordinary_resume_integrity()
    assert strategy.archive.result("population", "completed", expected.iterations) == expected
    for method in (strategy.run, strategy.resume):
        with pytest.raises(EvolutionError, match="archive_read_only"):
            method()
    with pytest.raises(EvolutionError, match="archive_read_only"):
        strategy.archive.write_state({"strategy": "population"})
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("recovery", [False, True])
def test_native_delivery_uses_read_only_population_validation(tmp_path, monkeypatch, recovery):
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    contract = _contract()
    child = controller.create_evolution_run(contract, workspace=tmp_path / "child")
    child, _ = controller.run_evolution(
        child.id, contract, lambda request: CandidateDraft("fixture = 1\n"),
        lambda *args: _report(0.5), _config(),
    )
    workspace = Path(child.workspace)
    if recovery:
        marker = workspace / ".evolution-seed-backup-v1"
        marker.mkdir()
        (marker / "retained.json").write_bytes(b"retained")
    before = _snapshot(workspace)
    events = controller.store.list_events(child.id)
    monkeypatch.setattr(CandidateArchive, "_recover_seed_publication", _forbidden)
    expected = "recovery_required" if recovery else "requires_bundle_candidate"
    with pytest.raises(EvolutionError, match=expected):
        controller._verified_bundle_evolution_delivery(child.id)
    assert _snapshot(workspace) == before
    assert controller.store.list_events(child.id) == events
