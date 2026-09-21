"""Workspace plans bind static declarations and never inspect or run a runner."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lunar_evolution.candidate_bundle import CandidateSourceBundle
from lunar_evolution.candidate_workspace_plan import (
    MAX_WORKSPACE_PLAN_BYTES,
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    build_candidate_workspace_plan,
    candidate_file_table_sha256,
    parse_candidate_workspace_plan,
    validate_candidate_workspace_plan,
)

CONTRACT = "a" * 64


def _bundle():
    return CandidateSourceBundle.from_dict({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT, "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })


def _plan(**kwargs):
    return build_candidate_workspace_plan(
        _bundle(), contract_sha256=CONTRACT, command=["/absent/python", "main.py"], **kwargs,
    )


def test_plan_serialization_embeds_bundle_and_derives_all_file_identity():
    plan = _plan()
    assert set(plan.to_dict()) == {
        "schema_version", "protocol", "bundle", "command", "environment", "timeout_seconds",
        "max_output_bytes", "workspace_cwd",
    }
    assert plan.bundle == _bundle()
    assert plan.contract_sha256 == CONTRACT
    assert plan.bundle_sha256 == _bundle().digest()
    assert plan.entrypoint == "main.py"
    assert plan.file_count == 1
    assert plan.total_bytes == 0
    assert plan.file_table_sha256 == candidate_file_table_sha256(_bundle())
    assert plan.environment == ()
    assert plan.to_dict()["environment"] == {}
    assert plan.to_dict()["bundle"] == _bundle().to_dict()
    content = json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert plan.digest() == hashlib.sha256(content.encode()).hexdigest()
    assert parse_candidate_workspace_plan(plan.to_dict()) == plan
    assert validate_candidate_workspace_plan(plan) == plan


def test_mapping_build_parse_validate_and_digest_are_pure_memory(monkeypatch):
    bundle = _bundle().to_dict()
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("opened a file"))
    monkeypatch.setattr(Path, "stat", lambda *_a, **_kw: pytest.fail("inspected a runner"))
    monkeypatch.setattr(Path, "lstat", lambda *_a, **_kw: pytest.fail("inspected a runner"))
    plan = build_candidate_workspace_plan(
        bundle, contract_sha256=CONTRACT, command=["/bin/sh", "-c", "", ""],
        environment={"EMPTY": "", "NONASCII": "你好"},
    )
    assert plan.command == ("/bin/sh", "-c", "", "")
    assert dict(plan.environment) == {"EMPTY": "", "NONASCII": "你好"}
    assert parse_candidate_workspace_plan(plan.to_dict()).digest() == plan.digest()
    assert validate_candidate_workspace_plan(plan).digest() == plan.digest()


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(bundle_sha256="b" * 64),
    lambda p: p.update(file_count=999),
    lambda p: p.update(unknown=True),
    lambda p: p.pop("bundle"),
    lambda p: p.update(schema_version=1),
    lambda p: p.update(protocol="unknown"),
    lambda p: p.update(workspace_cwd="src"),
    lambda p: p.update(environment=[]),
    lambda p: p.update(command="/bin/sh"),
    lambda p: p.update(command=[]),
    lambda p: p.update(command=["/bin/sh"] * 33),
    lambda p: p.update(command=["/bin/sh", "\x00"]),
    lambda p: p.update(command=["/bin/sh", "\ud800"]),
    lambda p: p.update(command=["/bin/sh", "é" * 2049]),
    lambda p: p.update(environment={"": "value"}),
    lambda p: p.update(environment={"A=B": "value"}),
    lambda p: p.update(environment={"A": "\x00"}),
    lambda p: p.update(environment={"A": "\ud800"}),
    lambda p: p.update(environment={"A": "x" * 4097}),
    lambda p: p.update(environment={"A" * 257: "value"}),
    lambda p: p.update(environment={f"A{i}": "" for i in range(129)}),
    lambda p: p["bundle"].update(entrypoint="absent.py"),
    lambda p: p["bundle"]["files"][0].update(path="../outside.py"),
])
def test_invalid_schema_and_text_are_rejected(mutation):
    payload = _plan().to_dict()
    mutation(payload)
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        parse_candidate_workspace_plan(payload)


@pytest.mark.parametrize("runner", ["", "python", "./python", "/bin/../python", "/bin//python", "/bin/./python"])
def test_runner_is_only_a_normalized_explicit_absolute_declaration(runner):
    payload = _plan().to_dict()
    payload["command"] = [runner]
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_runner_unsafe$"):
        parse_candidate_workspace_plan(payload)


@pytest.mark.parametrize("timeout", [True, None, "3", 0, -1, float("inf"), float("nan"), 86_401, pytest.param(10**10000, id="huge")])
def test_timeout_rejects_bool_nonfinite_and_overflow_without_escaping(timeout):
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        _plan(timeout_seconds=timeout)


@pytest.mark.parametrize("maximum", [True, None, "3", 0, -1, 1.5, 64 * 1024 * 1024 + 1])
def test_output_limit_requires_a_bounded_positive_integer(maximum):
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        _plan(max_output_bytes=maximum)


def test_exact_numeric_limits_and_canonical_environment_are_accepted():
    plan = _plan(timeout_seconds=86_400, max_output_bytes=64 * 1024 * 1024, environment={"Z": "z", "A": ""})
    assert plan.timeout_seconds == 86_400.0
    assert plan.environment == (("A", ""), ("Z", "z"))
    assert _plan(timeout_seconds=300).digest() == _plan(timeout_seconds=300.0).digest()


@pytest.mark.parametrize(("contract", "identity", "error"), [
    (None, None, "invalid"), ("", None, "invalid"), ("A" * 64, None, "invalid"),
    ("b" * 64, None, "contract_mismatch"), (CONTRACT, "", "invalid"),
    (CONTRACT, "b" * 64, "identity_mismatch"),
])
def test_builder_requires_caller_pins(contract, identity, error):
    with pytest.raises(CandidateWorkspaceError, match=f"^candidate_workspace_{error}$"):
        build_candidate_workspace_plan(
            _bundle(), command=["/bin/sh"], contract_sha256=contract,
            expected_bundle_sha256=identity,
        )


def test_builder_accepts_matching_pins_and_does_not_capture_process_environment(monkeypatch):
    monkeypatch.setenv("LUNAR_PLAN_TEST_SECRET", "must-not-capture")
    plan = build_candidate_workspace_plan(
        _bundle(), command=["/bin/sh"], contract_sha256=CONTRACT,
        expected_bundle_sha256=_bundle().digest(),
    )
    assert plan.environment == ()
    assert "must-not-capture" not in json.dumps(plan.to_dict())


@pytest.mark.parametrize("environment", [
    (("A", "one"), ("A", "two")), (("A",),), ("AB",), (("A", "B", "C"),),
])
def test_direct_dto_environment_pairs_do_not_silently_drop_duplicates(environment):
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        CandidateWorkspacePlan(_bundle(), ("/bin/sh",), environment=environment)


@pytest.mark.parametrize("mutation", [
    lambda p: object.__setattr__(p, "environment", (("A", "one"), ("A", "two"))),
    lambda p: object.__setattr__(p, "command", ("/bin/sh", "\x00")),
    lambda p: object.__setattr__(p, "timeout_seconds", 10**10000),
    lambda p: object.__setattr__(p, "bundle", None),
    lambda p: object.__setattr__(p.bundle, "entrypoint", "absent.py"),
    lambda p: object.__setattr__(p.bundle.files[0], "size", True),
])
def test_validation_and_digest_replay_all_typed_values(mutation):
    plan = _plan()
    mutation(plan)
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        validate_candidate_workspace_plan(plan)
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        plan.digest()


def test_constructor_detaches_caller_bundle_and_containers():
    bundle = _bundle()
    command = ["/bin/sh"]
    environment = {"A": ""}
    plan = CandidateWorkspacePlan(bundle, command, environment)
    command.append("changed")
    environment["A"] = "changed"
    object.__setattr__(bundle.files[0], "size", 999)
    assert plan.command == ("/bin/sh",)
    assert plan.environment == (("A", ""),)
    assert plan.total_bytes == 0


def test_bundle_and_runner_changes_both_change_plan_identity():
    first = _plan()
    payload = first.to_dict()
    payload["bundle"]["files"][0]["sha256"] = "b" * 64
    assert parse_candidate_workspace_plan(payload).digest() != first.digest()
    payload = first.to_dict()
    payload["command"][0] = "/some/other/runner"
    assert parse_candidate_workspace_plan(payload).digest() != first.digest()


@pytest.mark.parametrize("content", [
    b'{"bundle":{},"bundle":{}}', b'{"environment":{"A":"1","A":"2"}}',
    b'{"timeout_seconds":NaN}', b'{"timeout_seconds":Infinity}', b"\xff", b"{}", b"",
])
def test_file_parser_rejects_non_strict_json(tmp_path, content):
    source = tmp_path / "plan.json"
    source.write_bytes(content)
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        parse_candidate_workspace_plan(source)


def test_file_parser_is_bounded_and_roundtrips(tmp_path, monkeypatch):
    plan = _plan()
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unbounded read"))
    assert parse_candidate_workspace_plan(source) == plan
    with source.open("wb") as stream:
        stream.truncate(MAX_WORKSPACE_PLAN_BYTES + 1)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversized metadata read"))
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_too_large$"):
        parse_candidate_workspace_plan(source)


@pytest.mark.parametrize("kind", ["symlink", "ancestor", "fifo", "directory", "missing"])
def test_file_parser_rejects_unsafe_nodes(tmp_path, kind):
    source = tmp_path / "plan.json"
    if kind == "symlink":
        source.symlink_to(tmp_path / "absent")
    elif kind == "ancestor":
        (tmp_path / "actual").mkdir()
        (tmp_path / "actual" / "plan.json").write_text(json.dumps(_plan().to_dict()))
        (tmp_path / "link").symlink_to(tmp_path / "actual", target_is_directory=True)
        source = tmp_path / "link" / "plan.json"
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "directory":
        source.mkdir()
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_invalid$"):
        parse_candidate_workspace_plan(source)


def test_oversized_in_memory_plan_is_rejected():
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_too_large$"):
        _plan(environment={f"VAR{i}": "x" * 4096 for i in range(40)})
