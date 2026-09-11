"""Opt-in host policy gates CLI dispatch without changing native result authority."""

from __future__ import annotations

import argparse
import builtins
import json
import os
import shlex
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou import cli


def _argv(command: str, workspace: Path) -> list[str]:
    return [
        command, "suite.json", "baseline.json",
        "--subject-command", "subject", "--harness-command", "harness",
        "--requested-model", "GLM-5.2", "--workspace", str(workspace), "--json",
    ]


@pytest.mark.parametrize("command", ["effect-trial", "effect-deep-trial"])
def test_default_dispatch_does_not_import_guard_or_validate_new_paths(
    command, tmp_path, monkeypatch, capsys,
):
    original_import = builtins.__import__

    def reject_host_import(name, *args, **kwargs):
        assert name not in {"host_session", "host_awake", "famou.host_session", "famou.host_awake"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_host_import)
    payload = {"status": "failed", "score": None, "native": {"unchanged": True}}
    seen = []

    def operation(args):
        seen.append(args)
        return payload

    monkeypatch.setattr(cli, "_" + command.replace("-", "_"), operation)
    # New validation must not run even for malformed input on the legacy branch.
    assert cli.main([*_argv(command, tmp_path), "--case-source", "malformed"]) == 0
    assert len(seen) == 1
    assert json.loads(capsys.readouterr().out) == payload


def test_default_scope_returns_original_payload_identity():
    payload = {"score": None}
    assert cli._effect_host_scope(argparse.Namespace(), lambda args: payload) is payload


@pytest.mark.parametrize("command", ["effect-trial", "effect-deep-trial"])
@pytest.mark.parametrize("resume", [False, True])
def test_guard_spans_whole_operation_and_preserves_returned_native_failure(
    command, resume, tmp_path, monkeypatch, capsys,
):
    report = tmp_path / "session.jsonl"
    events = []

    @contextmanager
    def scope(path):
        assert path == report
        events.append("active")
        try:
            yield
        finally:
            events.append("released")

    monkeypatch.setitem(sys.modules, "famou.host_session", SimpleNamespace(host_execution=scope))

    def operation(args):
        assert events == ["active"]
        assert args.resume is resume
        events.append("operation")
        return {"status": "failed", "score": None, "failure": "native"}

    monkeypatch.setattr(cli, "_" + command.replace("-", "_"), operation)
    argv = [*_argv(command, tmp_path / "trial"), "--keep-awake-report", str(report)]
    if resume:
        argv.append("--resume")
    assert cli.main(argv) == 0
    assert events == ["active", "operation", "released"]
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed", "score": None, "failure": "native",
    }


@pytest.mark.parametrize("command", ["effect-trial", "effect-deep-trial"])
def test_failed_guard_entry_precedes_profile_environment_and_runner(
    command, tmp_path, monkeypatch, capsys,
):
    @contextmanager
    def scope(path):
        raise ValueError("host_acquisition_failed")
        yield  # pragma: no cover

    monkeypatch.setitem(sys.modules, "famou.host_session", SimpleNamespace(host_execution=scope))

    def forbidden(*args, **kwargs):
        pytest.fail("configuration/credentials/runner accessed before host gate")

    for name in ("_load_model_profile", "_effect_environment", "EffectTrialRunner",
                 "DeepEffectTrialRunner"):
        monkeypatch.setattr(cli, name, forbidden)
    assert cli.main([
        *_argv(command, tmp_path / "trial"),
        "--keep-awake-report", str(tmp_path / "host.jsonl"),
    ]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {"error": "host_acquisition_failed"}


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("location", ["inside", "same", "dotdot", "workspace_alias", "report_alias",
                                      "case_source", "case_source_alias"])
def test_report_location_rejected_before_journal_creation(
    resume, location, tmp_path, monkeypatch, capsys,
):
    workspace = tmp_path / "trial"
    source = tmp_path / "case"
    source.mkdir()
    report = workspace / "host.jsonl"
    if location == "same":
        report = workspace
    elif location == "dotdot":
        report = tmp_path / "other" / ".." / "trial" / "host.jsonl"
    elif location == "workspace_alias":
        (tmp_path / "alias").symlink_to(workspace, target_is_directory=True)
        workspace = tmp_path / "alias"
    elif location == "report_alias":
        (tmp_path / "alias").symlink_to(workspace, target_is_directory=True)
        report = tmp_path / "alias" / "host.jsonl"
    elif location == "case_source":
        report = source / "host.jsonl"
    elif location == "case_source_alias":
        (tmp_path / "alias").symlink_to(source, target_is_directory=True)
        source = tmp_path / "alias"
        report = tmp_path / "case" / "host.jsonl"
    if resume:
        (tmp_path / "trial").mkdir()

    def forbidden(*args, **kwargs):
        pytest.fail("scope or work entered for a disallowed journal path")

    monkeypatch.setitem(sys.modules, "famou.host_session", SimpleNamespace(host_execution=forbidden))
    monkeypatch.setattr(cli, "_effect_trial", forbidden)
    argv = [*_argv("effect-trial", workspace), "--case-source", f"case={source}",
            "--keep-awake-report", str(report)]
    if resume:
        argv.append("--resume")
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "report must be outside" in json.loads(captured.err)["error"]
    assert not (tmp_path / "trial" / "host.jsonl").exists()
    assert not (tmp_path / "case" / "host.jsonl").exists()


def test_location_validation_keeps_original_path_for_scope_symlink_checks(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    supplied = alias / "host.jsonl"
    seen = []

    @contextmanager
    def scope(path):
        seen.append(path)
        yield

    monkeypatch.setitem(sys.modules, "famou.host_session", SimpleNamespace(host_execution=scope))
    args = argparse.Namespace(keep_awake_report=supplied, workspace=tmp_path / "trial", case_source=[])
    assert cli._effect_host_scope(args, lambda args: {}) == {}
    assert seen == [supplied]


@pytest.mark.parametrize("protected", ["workspace", "case_source"])
@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("spelling,alias", [("Trial", "TRIAL"), ("caf\u00e9", "cafe\u0301")])
def test_report_filesystem_alias_rejected_before_scope(
    protected, missing, spelling, alias, tmp_path, monkeypatch, capsys,
):
    anchor = tmp_path / "Parent"
    anchor.mkdir()
    if not (tmp_path / "PARENT").exists() or not anchor.samefile(tmp_path / "PARENT"):
        pytest.skip("requires a case-insensitive filesystem")
    root = anchor / spelling
    report_root = tmp_path / "PARENT" / alias
    if not missing:
        root.mkdir()
        if not report_root.exists() or not root.samefile(report_root):
            pytest.skip("filesystem does not alias these directory names")

    def forbidden(*args, **kwargs):
        pytest.fail("aliased protected directory accepted for journal")

    monkeypatch.setitem(sys.modules, "famou.host_session", SimpleNamespace(host_execution=forbidden))
    monkeypatch.setattr(cli, "_effect_trial", forbidden)
    workspace = root if protected == "workspace" else tmp_path / "workspace"
    argv = [*_argv("effect-trial", workspace), "--keep-awake-report", str(report_root / "host.jsonl")]
    if protected == "case_source":
        argv += ["--case-source", f"case={root}"]
    assert cli.main(argv) == 2
    assert "report must be outside" in json.loads(capsys.readouterr().err)["error"]
    assert not (report_root / "host.jsonl").exists()


def test_read_only_preflight_has_no_guard_option(tmp_path):
    argv = [
        "effect-preflight", "suite.json", "baseline.json", "--subject-command", "subject",
        "--harness-command", "harness", "--requested-model", "GLM-5.2",
        "--harness-python", sys.executable, "--json",
    ]
    assert not hasattr(cli.build_parser().parse_args(argv), "keep_awake_report")
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args([
            *argv, "--keep-awake-report", str(tmp_path / "host.jsonl"),
        ])
    assert error.value.code == 2


@pytest.mark.parametrize("command,runner_name", [
    ("effect-trial", "EffectTrialRunner"), ("effect-deep-trial", "DeepEffectTrialRunner"),
])
@pytest.mark.parametrize("configuration_failure", [False, True])
def test_real_scope_journal_surrounds_cli_configuration_and_runner(
    command, runner_name, configuration_failure, tmp_path, monkeypatch, capsys,
):
    from famou import host_session

    report = tmp_path / "host.jsonl"
    calls = []
    native = {"status": "failed", "scores": None, "failure": "native_result"}
    evidence = {
        "backend": "macos_iokit", "assertion_type": "PreventUserIdleSystemSleep",
        "assertion_id": 17, "owner_pid": os.getpid(), "level": 255, "verified": True,
    }

    class Guard:
        def acquire(self):
            calls.append("acquire")
            return evidence

        def verify(self):
            calls.append("verify")
            return evidence

        def release(self):
            calls.append("release")

    factory = host_session.host_execution
    monkeypatch.setattr(host_session, "host_execution", lambda path: factory(path, guard=Guard()))

    def load_profile(path):
        assert calls == ["acquire"]
        assert [json.loads(line)["event"] for line in report.read_text().splitlines()] == [
            "starting", "active",
        ]
        calls.append("configuration")
        if configuration_failure:
            raise ValueError("original configuration failure")

    class Runner:
        def __init__(self, *args, **kwargs):
            assert calls == ["acquire", "configuration"]
            calls.append("runner")

        def run(self):
            return SimpleNamespace(to_dict=lambda: native)

    monkeypatch.setattr(cli, "_load_model_profile", load_profile)
    monkeypatch.setattr(cli, runner_name, Runner)
    argv = _argv(command, tmp_path / "trial")
    for flag in ("--subject-command", "--harness-command"):
        argv[argv.index(flag) + 1] = shlex.join([str(Path(sys.executable).resolve()), "-c", "pass"])
    result = cli.main([
        *argv, "--keep-awake-report", str(report),
    ])
    captured = capsys.readouterr()
    journal_text = report.read_text()
    journal = [json.loads(line) for line in journal_text.splitlines()]
    assert [item["event"] for item in journal] == ["starting", "active", "closed"]
    assert calls[-2:] == ["verify", "release"]
    assert "original configuration failure" not in journal_text
    assert "native_result" not in journal_text
    if configuration_failure:
        assert result == 2
        assert journal[-1]["work_outcome"] == "raised"
        assert json.loads(captured.err)["error"] == "original configuration failure"
        assert "runner" not in calls
    else:
        assert result == 0, captured.err
        assert journal[-1]["work_outcome"] == "returned"
        assert json.loads(captured.out) == native
