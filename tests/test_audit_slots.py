from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from lunar_evolution import _audit_slots as module
from lunar_evolution._audit_slots import audit_execution_slots


def _fixture(tmp_path, *, run=".bundle-run-0123456789abcdef01234567", evaluation=".candidate-evaluation-0123456789abcdef01234567"):
    child = tmp_path / "child"
    run_root = child / "evolution" / "bundle-attempts" / run
    (run_root / "attempt").mkdir(parents=True)
    (run_root / "evaluations" / evaluation).mkdir(parents=True)
    (run_root / "plan.json").write_bytes(b"{}")
    (run_root / "admission.json").write_bytes(b"{}")
    return child, {
        "plan_path": f"evolution/bundle-attempts/{run}/plan.json",
        "admission_path": f"evolution/bundle-attempts/{run}/admission.json",
        "execution_path": f"evolution/bundle-attempts/{run}/attempt",
        "evaluation_path": f"evolution/bundle-attempts/{run}/evaluations/{evaluation}",
    }


def _audit(child, paths):
    return audit_execution_slots(child, **paths)


def test_one_complete_slot_is_verified(tmp_path):
    child, paths = _fixture(tmp_path)
    assert _audit(child, paths) == {"status": "verified", "reason": None}


def test_optional_cleanup_receipt_is_checked_without_becoming_a_second_slot(tmp_path):
    child, paths = _fixture(tmp_path)
    cleanup = child / paths["execution_path"] / "cleanup.json"
    cleanup.write_bytes(b"cleanup")
    paths["cleanup_path"] = paths["execution_path"] + "/cleanup.json"
    assert _audit(child, paths) == {"status": "verified", "reason": None}
    paths["cleanup_path"] = paths["execution_path"] + "/wrong.json"
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_request_invalid"}


def test_missing_slot_or_required_artifact_is_unverifiable(tmp_path):
    child, paths = _fixture(tmp_path)
    paths["plan_path"] = paths["plan_path"].replace("plan.json", "missing.json")
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_request_invalid"}
    child, paths = _fixture(tmp_path / "missing")
    (child / paths["plan_path"]).unlink()
    assert _audit(child, paths)["status"] == "unverifiable"


def test_second_empty_or_failed_attempt_is_rejected(tmp_path):
    child, paths = _fixture(tmp_path)
    attempts = child / "evolution" / "bundle-attempts"
    (attempts / ".bundle-run-fedcba9876543210fedcba98").mkdir()
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_extra_attempt"}


def test_extra_file_or_symlink_under_attempts_is_rejected(tmp_path):
    child, paths = _fixture(tmp_path)
    attempts = child / "evolution" / "bundle-attempts"
    (attempts / "stray").write_bytes(b"x")
    assert _audit(child, paths)["reason"] == "slot_extra_attempt"
    child, paths = _fixture(tmp_path / "symlink")
    attempts = child / "evolution" / "bundle-attempts"
    os.symlink("/tmp", attempts / ".bundle-run-fedcba9876543210fedcba98")
    assert _audit(child, paths)["reason"] == "slot_extra_attempt"


@pytest.mark.parametrize("field, replacement", [
    ("plan_path", "/absolute/plan.json"),
    ("plan_path", "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/../plan.json"),
    ("admission_path", "evolution\\bundle-attempts\\.bundle-run-0123456789abcdef01234567\\admission.json"),
    ("execution_path", "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/attempt/extra"),
    ("evaluation_path", "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/evaluations/.candidate-evaluation-bad"),
])
def test_paths_must_be_one_native_slot(field, replacement, tmp_path):
    child, paths = _fixture(tmp_path)
    paths[field] = replacement
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_request_invalid"}


def test_paths_must_share_run_and_evaluation_identity(tmp_path):
    child, paths = _fixture(tmp_path)
    paths["admission_path"] = paths["admission_path"].replace("0123456789abcdef01234567", "fedcba9876543210fedcba98")
    assert _audit(child, paths)["reason"] == "slot_request_invalid"
    child, paths = _fixture(tmp_path / "eval")
    paths["evaluation_path"] = paths["evaluation_path"].replace("0123456789abcdef01234567", "fedcba9876543210fedcba98")
    assert _audit(child, paths)["reason"] == "slot_request_invalid"


def test_symlinked_required_directory_is_unverifiable(tmp_path):
    child, paths = _fixture(tmp_path)
    attempt = child / "evolution" / "bundle-attempts" / ".bundle-run-0123456789abcdef01234567" / "attempt"
    attempt.rmdir()
    os.symlink("/tmp", attempt)
    report = _audit(child, paths)
    assert report["status"] == "unverifiable"


def test_second_evaluation_identity_is_rejected(tmp_path):
    child, paths = _fixture(tmp_path)
    evaluation_root = child / "evolution" / "bundle-attempts" / ".bundle-run-0123456789abcdef01234567" / "evaluations"
    (evaluation_root / ".candidate-evaluation-fedcba9876543210fedcba98").mkdir()
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_extra_attempt"}


def test_empty_evaluation_and_attempt_directories_are_still_structurally_checked(tmp_path):
    child, paths = _fixture(tmp_path)
    # Content validity belongs to the native record/evaluation inspectors; this helper only
    # proves that their exact directories are present and uniquely identified.
    assert _audit(child, paths)["status"] == "verified"


@pytest.mark.parametrize("name", ["plan.json", "admission.json"])
def test_required_record_file_never_follows_symlink_or_fifo(tmp_path, name):
    child, paths = _fixture(tmp_path)
    run = child / paths["plan_path"]
    path = run.parent / name
    path.unlink()
    path.symlink_to(tmp_path / "private-missing")
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_entry_unsafe"}
    path.unlink()
    os.mkfifo(path)
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_entry_unsafe"}


def test_audit_opens_only_readonly_descriptors_and_retains_identical_bytes(tmp_path, monkeypatch):
    child, paths = _fixture(tmp_path)
    before = {path.relative_to(child): (path.stat().st_ino, path.read_bytes())
              for path in child.rglob("*") if path.is_file()}
    opened = []
    actual_open = os.open

    def checked(path, flags, *args, **kwargs):
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        descriptor = actual_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(module.os, "open", checked)
    assert _audit(child, paths)["status"] == "verified"
    assert _audit(child, paths)["status"] == "verified"
    assert before == {path.relative_to(child): (path.stat().st_ino, path.read_bytes())
                      for path in child.rglob("*") if path.is_file()}
    for descriptor in set(opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_extra_slot_scan_stops_after_second_entry(tmp_path, monkeypatch):
    child, paths = _fixture(tmp_path)
    actual_scandir = os.scandir

    @contextmanager
    def bounded(fd):
        with actual_scandir(fd) as entries:
            first = next(entries)

            def values():
                yield first
                yield first
                pytest.fail("scanner traversed more than two entries")

            yield values()

    monkeypatch.setattr(module.os, "scandir", bounded)
    assert _audit(child, paths) == {"status": "failed", "reason": "slot_extra_attempt"}


def test_directory_identity_replacement_is_not_accepted(tmp_path, monkeypatch):
    child, paths = _fixture(tmp_path)
    run = (child / paths["plan_path"]).parent
    actual_scan = module._one_directory
    replaced = False

    def replace_after_scan(chain, expected, pattern):
        nonlocal replaced
        found = actual_scan(chain, expected, pattern)
        if not replaced:
            replaced = True
            run.rename(run.with_name(".replaced"))
            run.mkdir()
        return found

    monkeypatch.setattr(module, "_one_directory", replace_after_scan)
    assert _audit(child, paths) == {"status": "unverifiable", "reason": "slot_changed"}


def test_interruption_releases_every_directory_descriptor(tmp_path, monkeypatch):
    child, paths = _fixture(tmp_path)
    opened = []
    actual_open = os.open

    def checked(*args, **kwargs):
        descriptor = actual_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "open", checked)
    monkeypatch.setattr(module, "_regular", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _audit(child, paths)
    for descriptor in set(opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)
