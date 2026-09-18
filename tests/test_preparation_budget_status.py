"""Preparation policy remains separate from observations and frozen execution profiles."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_local_diagnostics import replace_payload
from test_preparation_recovery_cli import run_cli, runtime_calls, snapshot
from test_preparation_wall_budget import Clock

from famou import automatic_solve_bundle as automatic
from famou import cli
from famou.store import Store


def test_budgets_visible_before_preparation_and_status_is_readonly(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    code, waiting, _ = run_cli(capsys, [*args, "--evaluator-preparation-timeout", "7"])
    assert code == 0 and waiting["status"] == "awaiting_input"
    expected = {
        "candidate_timeout": {"seconds": 3.0, "source": "explicit"},
        "evaluator_preparation_timeout": {"seconds": 7.0, "source": "explicit"},
        "evaluator_preparation_wall_timeout": {"seconds": 74.0, "source": "default"},
    }
    assert waiting["evolution"]["preparation_budgets"] == expected
    store = Store(tmp_path / "home/state.db")
    parent = store.get_run(waiting["run_id"])
    before, calls = snapshot(store, parent.id, parent.workspace), runtime_calls(runtime)
    code, status, _ = run_cli(capsys, ["status", parent.id, "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and status["evolution"]["preparation_budgets"] == expected
    assert "preparation" not in status["evolution"]
    assert cli.main(["status", parent.id, "--home", str(tmp_path / "home")]) == 0
    text = capsys.readouterr().out
    assert "candidate_timeout: 3.0 (explicit)" in text
    assert "evaluator_preparation_timeout: 7.0 (explicit)" in text
    assert "evaluator_preparation_wall_timeout: 74.0 (default)" in text
    assert snapshot(store, parent.id, parent.workspace) == before
    assert runtime_calls(runtime) == calls


def test_legacy_budget_status_never_invents_a_wall_deadline(tmp_path, monkeypatch, capsys):
    _, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    _, waiting, _ = run_cli(capsys, args)
    store = Store(tmp_path / "home/state.db")
    event = next(item for item in store.list_events(waiting["run_id"])
                 if item["type"] == "evolution_requested")
    legacy = {key: value for key, value in event["payload"].items()
              if not key.startswith("evaluator_preparation_") and key != "timeout_source"}
    replace_payload(store, event, legacy)
    assert cli._preparation_budgets_payload(store, waiting["run_id"]) == {
        "candidate_timeout": {"seconds": 3.0, "source": "persisted"},
        "evaluator_preparation_timeout": {"seconds": 3.0, "source": "legacy"},
        "evaluator_preparation_wall_timeout": {"seconds": None, "source": "legacy"},
    }
    assert cli.main(["status", waiting["run_id"], "--home", str(tmp_path / "home")]) == 0
    assert "evaluator_preparation_wall_timeout: unbounded (legacy)" in capsys.readouterr().out
    assert cli._latest_evolution_request(store, waiting["run_id"]) == legacy


@pytest.mark.parametrize("field,value", [
    ("timeout", True), ("timeout", 0), ("timeout", float("inf")), ("timeout", 10**400),
    ("evaluator_preparation_timeout", "private-secret"),
    ("evaluator_preparation_timeout", None),
    ("evaluator_preparation_wall_timeout", 2),
    ("evaluator_preparation_wall_timeout", 86401),
    ("evaluator_preparation_wall_timeout", None),
    ("evaluator_preparation_timeout_source", ["private-secret"]),
    ("evaluator_preparation_wall_timeout_source", "private-secret"),
    ("evaluator_preparation_wall_timeout_source", "persisted"),
])
def test_bad_budget_policy_is_not_projected(monkeypatch, field, value):
    request = cli._evolution_request_payload(cli.build_parser().parse_args([
        "solve", "optimize", "--evolve", "--multi-file", "--timeout", "3",
    ]))
    changed = copy.deepcopy(request)
    changed[field] = value
    monkeypatch.setattr(cli, "_latest_evolution_request", lambda *_: changed)
    assert cli._preparation_budgets_payload(None, "parent") is None


@pytest.mark.parametrize("option", ["--evaluator-preparation-timeout", "--evaluator-preparation-wall-timeout"])
def test_preparation_option_without_evolution_rejected_before_state(tmp_path, monkeypatch, capsys, option):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid mode must not construct a runtime")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main(["solve", "optimize", option, "7", "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "--multi-file" in capsys.readouterr().err
    assert not (tmp_path / "home/state.db").exists()


def test_wall_expiry_status_and_explicit_resume_share_policy(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    clock = Clock()
    monkeypatch.setattr(automatic, "monotonic", clock)
    original = runtime.run

    def expire(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        if "frozen local evaluator bundle" in prompt:
            clock.advance(10)
        return result

    monkeypatch.setattr(runtime, "run", expire)
    code, failed, _ = run_cli(capsys, [*args, "--evaluator-preparation-timeout", "7",
                                    "--evaluator-preparation-wall-timeout", "10"])
    assert code == 1 and failed["status"] == "failed" and failed["run_status"] == "running"
    preparation = failed["evolution"]["preparation"]
    assert preparation["error_category"] == "preparation_timeout"
    assert preparation["recoverable"] is True
    assert runtime.generator_calls == runtime.audit_calls == 0
    workspace = Path(failed["workspace"])
    assert not (workspace / "bundle-profile.json").exists()
    assert not (workspace / "evolution-run").exists()
    store = Store(tmp_path / "home/state.db")
    before = snapshot(store, failed["run_id"], workspace)
    status_args = ["status", failed["run_id"], "--home", str(tmp_path / "home")]
    _, status, _ = run_cli(capsys, [*status_args, "--json"])
    assert status["evolution"]["preparation"] == preparation
    assert cli.main(status_args) == 0
    assert "preparation_wall_failure: wall_timeout elapsed_ms=10000 wall_timeout_ms=10000" in capsys.readouterr().out
    assert snapshot(store, failed["run_id"], workspace) == before
    monkeypatch.setattr(runtime, "run", original)
    code, resumed, _ = run_cli(capsys, ["resume", failed["run_id"], "--runtime", "mock",
                                     "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and resumed["status"] == "succeeded"
    assert resumed["evolution"]["preparation"]["status"] == "prepared"
    assert resumed["evolution"]["preparation_budgets"] == failed["evolution"]["preparation_budgets"]
    assert runtime.contract_calls == 1 and runtime.generator_calls == 4
    starts = [item["payload"] for item in store.list_events(failed["run_id"])
              if item["type"] == "bundle_preparation_started"]
    assert len(starts) == 2 and starts[0]["attempt_id"] != starts[1]["attempt_id"]
    assert starts[0]["preparation_budgets"] == starts[1]["preparation_budgets"]
