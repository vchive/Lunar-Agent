"""Optional byte admission is read-only, bounded, and does not follow replaced path names."""
from __future__ import annotations

import hashlib
import os
import subprocess

import pytest

from lunar_evolution import _benchmark_files as files
from lunar_evolution.candidate_bundle import CandidateSourceBundle
from lunar_evolution.candidate_execution import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionError,
    CandidateExecutionInput,
    admit_candidate_execution,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan


def _plan():
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": "a" * 64, "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })
    return build_candidate_workspace_plan(
        bundle, contract_sha256="a" * 64, command=["/absent/runner", "main.py"],
        timeout_seconds=5, max_output_bytes=1024,
    )


def _fields(inputs=()):
    return {
        "inputs": inputs, "dependency_sha256": "b" * 64, "environment_sha256": "c" * 64,
        "evaluator": CandidateEvaluatorPin("exact-harness", "d" * 64),
        "output_contract_sha256": "e" * 64,
        "budget": CandidateExecutionBudget(5, 1024, 1024, 1),
    }


def _item(target="data/input.bin", content=b"fixture"):
    return CandidateExecutionInput(target, "fixture", len(content), hashlib.sha256(content).hexdigest())


def _admit(root, inputs=()):
    return admit_candidate_execution(_plan(), input_root=root, **_fields(inputs))


def test_verifies_binary_bytes_without_staging_or_reading_undeclared_files(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    (root / "data").mkdir(parents=True)
    content = bytes([0, 255, 128]) + b"private input payload"
    (root / "data/input.bin").write_bytes(content)
    (root / "main.py").write_text("raise AssertionError('candidate executed')")
    (root / "undeclared").symlink_to(tmp_path / "missing")
    home = tmp_path / "unused-home"
    monkeypatch.setenv("LUNAR_HOME", str(home))
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_kw: pytest.fail("process started"))
    monkeypatch.setattr(os, "system", lambda *_a, **_kw: pytest.fail("shell started"))
    reader = files.read_regular_file
    seen = []

    def checked_reader(path, maximum, *, exact_size=False):
        seen.append((path, maximum, exact_size))
        return reader(path, maximum, exact_size=exact_size)

    monkeypatch.setattr(files, "read_regular_file", checked_reader)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    result = _admit(root, [_item(content=content)])
    assert result.inputs_verified is True
    assert result.observed_inputs == (_item(content=content),)
    assert result.input_count == 1
    assert result.total_input_bytes == len(content)
    assert seen == [(root / "data/input.bin", len(content), True)]
    assert str(tmp_path) not in str(result.to_dict())
    assert "private input payload" not in str(result.to_dict())
    assert not home.exists()
    assert before == sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))


def test_structural_admission_and_verified_empty_input_set_are_distinct(tmp_path):
    plan = _plan()
    admission = build_candidate_execution_admission(plan, **_fields())
    structural = admit_candidate_execution(admission, plan=plan)
    verified = admit_candidate_execution(admission, plan=plan, input_root=tmp_path)
    assert structural.admission_sha256 == verified.admission_sha256
    assert structural.observed_inputs is None
    assert structural.to_dict()["observed_inputs"] is None
    assert structural.inputs_verified is False
    assert verified.observed_inputs == ()
    assert verified.to_dict()["observed_inputs"] == []
    assert verified.inputs_verified is True


@pytest.mark.parametrize(("content", "error"), [
    (None, "input_missing"), (b"different", "input_changed"), (b"", "input_changed"),
    (b"fixture-extra", "input_changed"), (b"fixturE", "input_changed"),
])
def test_missing_wrong_size_and_digest_fail_with_fixed_codes(tmp_path, content, error):
    root = tmp_path / "inputs"
    (root / "data").mkdir(parents=True)
    if content is not None:
        (root / "data/input.bin").write_bytes(content)
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{error}$"):
        _admit(root, [_item()])


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_input_leaves_must_be_regular_files(tmp_path, kind):
    root = tmp_path / "inputs"
    (root / "data").mkdir(parents=True)
    target = root / "data/input.bin"
    if kind == "symlink":
        source = tmp_path / "external"
        source.write_bytes(b"fixture")
        target.symlink_to(source)
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_unsafe$"):
        _admit(root, [_item()])


@pytest.mark.parametrize("level", ["root", "ancestor", "input-directory"])
def test_no_symlink_components_are_followed(tmp_path, level):
    real = tmp_path / "real"
    (real / "data").mkdir(parents=True)
    (real / "data/input.bin").write_bytes(b"fixture")
    if level == "root":
        root = tmp_path / "alias"
        root.symlink_to(real, target_is_directory=True)
    elif level == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        root = alias / "real"
    else:
        root = tmp_path / "input-root"
        root.mkdir()
        (root / "data").symlink_to(real / "data", target_is_directory=True)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_unsafe$"):
        _admit(root, [_item()])


@pytest.mark.parametrize("kind", ["missing", "file", "symlink", "ancestor-symlink"])
def test_empty_inputs_do_not_skip_root_verification(tmp_path, kind):
    root = tmp_path / "root"
    if kind == "file":
        root.write_bytes(b"")
    elif kind == "symlink":
        root.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "ancestor-symlink":
        (tmp_path / "real").mkdir()
        root.symlink_to(tmp_path, target_is_directory=True)
        root = root / "real"
    error = "input_missing" if kind == "missing" else "input_unsafe"
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{error}$"):
        _admit(root)


def test_parent_traversal_root_is_rejected_without_normalizing_it(tmp_path):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_unsafe$"):
        _admit(tmp_path / "absent" / "..")


def test_oversized_file_is_rejected_before_its_bytes_are_read(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/input.bin").write_bytes(b"fixture-extra")
    monkeypatch.setattr(files.os, "read", lambda *_a, **_kw: pytest.fail("oversized input read"))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_changed$"):
        _admit(tmp_path, [_item()])


@pytest.mark.parametrize("mutation", ["replace-leaf", "modify-leaf", "replace-directory", "delete-leaf"])
def test_file_identity_changes_during_bounded_read_are_rejected(tmp_path, monkeypatch, mutation):
    root = tmp_path / "inputs"
    (root / "data").mkdir(parents=True)
    source = root / "data/input.bin"
    source.write_bytes(b"fixture")
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    original_read = os.read
    changed = False

    def read_and_mutate(descriptor, count):
        nonlocal changed
        info = os.fstat(descriptor)
        if not changed and (info.st_dev, info.st_ino) == source_identity:
            changed = True
            if mutation == "replace-leaf":
                replacement = source.with_name("replacement")
                replacement.write_bytes(b"fixture")
                replacement.replace(source)
            elif mutation == "modify-leaf":
                source.write_bytes(b"fixturE")
            elif mutation == "replace-directory":
                (root / "data").rename(root / "old-data")
                (root / "data").mkdir()
                source.write_bytes(b"fixture")
            else:
                source.unlink()
        return original_read(descriptor, count)

    monkeypatch.setattr(files.os, "read", read_and_mutate)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_changed$"):
        _admit(root, [_item()])
    assert changed is True


def test_matching_replay_pins_verify_same_bytes_without_rewriting(tmp_path):
    (tmp_path / "data").mkdir()
    source = tmp_path / "data/input.bin"
    source.write_bytes(b"fixture")
    info = source.stat()
    plan = _plan()
    admission = build_candidate_execution_admission(plan, **_fields([_item()]))
    result = admit_candidate_execution(
        admission.to_dict(), plan=plan.to_dict(), input_root=tmp_path,
        expected_plan_sha256=plan.digest(), expected_bundle_sha256=plan.bundle_sha256,
        expected_contract_sha256=plan.contract_sha256, expected_dependency_sha256="b" * 64,
        expected_environment_sha256="c" * 64, expected_evaluator=admission.evaluator,
        expected_evaluator_sha256=admission.evaluator.fingerprint,
        expected_evaluator_kind=admission.evaluator.kind,
        expected_output_contract_sha256="e" * 64, expected_admission_sha256=admission.digest(),
    )
    assert result.inputs_verified is True
    after = source.stat()
    assert (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )


def test_direct_plan_requires_explicit_fields_and_does_not_open_root(monkeypatch):
    plan = _plan()
    monkeypatch.setattr(files, "absolute_path", lambda *_a, **_kw: pytest.fail("input path touched"))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_invalid$"):
        admit_candidate_execution(plan, input_root="/absent")
