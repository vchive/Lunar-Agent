"""Preparation wall budgets retain their policy across conversational continuation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_recovery_cli import snapshot

from famou import cli
from famou.evolution import EvolutionError
from famou.store import Store


def request_for(*arguments):
    args = cli.build_parser().parse_args([
        "solve", "optimize", "--evolve", "--multi-file", *arguments,
    ])
    return cli._evolution_request_payload(args)


@pytest.mark.parametrize(("arguments", "candidate", "request_seconds", "wall", "sources"), [
    ([], 900.0, 900.0, 1860.0, ("default", "default", "default")),
    (["--timeout", "3"], 3.0, 3.0, 66.0, ("explicit", "default", "default")),
    (["--timeout", "3", "--evaluator-preparation-timeout", "7"],
     3.0, 7.0, 74.0, ("explicit", "explicit", "default")),
    (["--evaluator-preparation-timeout", "50000"],
     900.0, 50000.0, 86400.0, ("default", "explicit", "default")),
    (["--timeout", "3", "--evaluator-preparation-timeout", "7",
      "--evaluator-preparation-wall-timeout", "80"],
     3.0, 7.0, 80.0, ("explicit", "explicit", "explicit")),
])
def test_fresh_request_resolves_and_persists_budgets(arguments, candidate, request_seconds, wall, sources):
    payload = request_for(*arguments)

    assert payload["timeout"] == candidate
    assert payload["evaluator_preparation_timeout"] == request_seconds
    assert payload["evaluator_preparation_wall_timeout"] == wall
    assert tuple(payload[name + "_source"] for name in (
        "timeout", "evaluator_preparation_timeout", "evaluator_preparation_wall_timeout",
    )) == sources


@pytest.mark.parametrize("command", [
    ["solve", "--resume", "--run-id", "parent"],
    ["resume", "parent"],
    ["answer", "parent", "continue"],
])
@pytest.mark.parametrize("repeat_budget", [False, True])
def test_continuation_restores_persisted_wall_policy(command, repeat_budget):
    request = request_for("--timeout", "3", "--evaluator-preparation-timeout", "7",
                          "--evaluator-preparation-wall-timeout", "80")
    supplied = ["--evaluator-preparation-wall-timeout", "80"] if repeat_budget else []
    args = cli.build_parser().parse_args([*command, *supplied])
    cli._validate_conversational_bundle_request(args, request)
    cli._validate_evolution_override(args, request)
    restored = cli._evolution_args(args, request)

    assert restored.timeout == 3.0
    assert restored.evaluator_preparation_timeout == 7.0
    assert restored.evaluator_preparation_wall_timeout == 80.0


@pytest.mark.parametrize("value", ["0", "-1", "86401", "nan", "inf"])
@pytest.mark.parametrize("command", [
    ["solve", "optimize", "--evolve", "--multi-file"],
    ["resume", "parent"],
    ["answer", "parent", "continue"],
])
def test_invalid_wall_timeout_fails_before_database_or_runtime(
    tmp_path, monkeypatch, capsys, value, command,
):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid wall timeout must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main([
        *command, "--evaluator-preparation-wall-timeout", value,
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "evaluator-preparation-wall-timeout" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("arguments", [
    ["--timeout", "10", "--evaluator-preparation-wall-timeout", "9"],
    ["--evaluator-preparation-timeout", "20", "--evaluator-preparation-wall-timeout", "19"],
    ["--evaluator-preparation-wall-timeout", "899"],
])
def test_wall_budget_cannot_be_smaller_than_resolved_request(
    tmp_path, monkeypatch, capsys, arguments,
):
    def forbidden(*args, **kwargs):
        pytest.fail("inconsistent preparation budgets must not construct a runtime")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main([
        "solve", "optimize", "--evolve", "--multi-file", *arguments,
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "at least" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


def test_legacy_handoff_is_unbounded_and_rejects_new_wall_policy():
    request = request_for("--timeout", "3")
    for name in ("evaluator_preparation_timeout", "evaluator_preparation_wall_timeout"):
        del request[name]
        del request[name + "_source"]
    del request["timeout_source"]
    parser = cli.build_parser()
    args = parser.parse_args(["resume", "parent"])
    cli._validate_evolution_override(args, request)
    restored = cli._evolution_args(args, request)
    assert restored.evaluator_preparation_timeout == 3.0
    assert restored.evaluator_preparation_wall_timeout is None

    supplied = parser.parse_args(["resume", "parent", "--evaluator-preparation-wall-timeout", "66"])
    with pytest.raises(EvolutionError, match="evaluator_preparation_wall_timeout"):
        cli._validate_evolution_override(supplied, request)


@pytest.mark.parametrize("command", ["solve", "resume", "answer"])
@pytest.mark.parametrize("legacy", [False, True])
def test_wall_override_mismatch_preserves_events_artifacts_and_pending_answer(
    tmp_path, monkeypatch, capsys, command, legacy,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    args.extend(("--evaluator-preparation-wall-timeout", "80"))
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    parent = initial["run_id"]
    if legacy:
        event = next(event for event in store.list_events(parent)
                     if event["type"] == "evolution_requested")
        payload = event["payload"]
        del payload["evaluator_preparation_wall_timeout"]
        del payload["evaluator_preparation_wall_timeout_source"]
        with store._connect() as connection:
            connection.execute("UPDATE events SET payload = ? WHERE id = ?",
                               (json.dumps(payload), event["id"]))
    workspace = Path(initial["workspace"])
    before = snapshot(store, parent, workspace)
    pending = store.pending_input(parent)

    def forbidden(*args, **kwargs):
        pytest.fail("a changed preparation policy must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    followup = {
        "solve": ["solve", "--resume", "--run-id", parent],
        "resume": ["resume", parent],
        "answer": ["answer", parent, "maximize value"],
    }[command]
    assert cli.main([
        *followup, "--evaluator-preparation-wall-timeout", "81",
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "evaluator_preparation_wall_timeout" in json.loads(capsys.readouterr().err)["error"]
    assert snapshot(store, parent, workspace) == before
    assert store.pending_input(parent) == pending
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls) == (1, 0, 0)


@pytest.mark.parametrize("value", [None, False, "80", 0, 86401, float("nan")])
def test_invalid_persisted_wall_budget_is_rejected(value):
    request = request_for("--timeout", "3")
    request["evaluator_preparation_wall_timeout"] = value
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match="evaluator_preparation_wall_timeout"):
        cli._validate_conversational_bundle_request(args, request)


def test_persisted_wall_budget_cannot_be_less_than_request():
    request = request_for("--timeout", "3", "--evaluator-preparation-timeout", "7")
    request["evaluator_preparation_wall_timeout"] = 6.0
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match="at least"):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("name", [
    "timeout_source", "evaluator_preparation_timeout_source",
    "evaluator_preparation_wall_timeout_source",
])
@pytest.mark.parametrize("source", [None, [], "legacy"])
def test_persisted_invalid_budget_origin_is_rejected(name, source):
    request = request_for()
    request[name] = source
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match=name):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("name", [
    "timeout", "evaluator_preparation_timeout", "evaluator_preparation_wall_timeout",
])
def test_persisted_budget_origin_without_value_is_rejected(name):
    request = request_for()
    del request[name]
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match=name + "_source"):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("value", [None, True, 0, -1, float("nan"), "bad", 10**400])
@pytest.mark.parametrize("command", ["solve", "resume", "answer"])
def test_invalid_legacy_request_fallback_rejects_before_runtime_or_mutation(
    tmp_path, monkeypatch, capsys, value, command,
):
    _, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    parent = initial["run_id"]
    event = next(event for event in store.list_events(parent)
                 if event["type"] == "evolution_requested")
    request = event["payload"]
    for name in ("evaluator_preparation_timeout", "evaluator_preparation_wall_timeout"):
        del request[name]
        del request[name + "_source"]
    del request["timeout_source"]
    request["timeout"] = value
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?",
                           (json.dumps(request), event["id"]))
    workspace = Path(initial["workspace"])
    before = snapshot(store, parent, workspace)
    pending = store.pending_input(parent)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid legacy preparation policy must not construct a runtime")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    followup = {
        "solve": ["solve", "--resume", "--run-id", parent],
        "resume": ["resume", parent],
        "answer": ["answer", parent, "maximize value"],
    }[command]
    assert cli.main([
        *followup, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "timeout" in json.loads(capsys.readouterr().err)["error"]
    after = snapshot(store, parent, workspace)
    # Canonical serialization also compares malformed NaN event values reliably.
    assert json.dumps(after[0], sort_keys=True) == json.dumps(before[0], sort_keys=True)
    assert after[1:] == before[1:]
    assert store.pending_input(parent) == pending


@pytest.mark.parametrize("repeat_mode", [False, True])
@pytest.mark.parametrize("budget_options", [
    [], ["--evaluator-preparation-timeout", "7"],
    ["--evaluator-preparation-wall-timeout", "80"],
    ["--evaluator-preparation-timeout", "7", "--evaluator-preparation-wall-timeout", "80"],
])
def test_resume_with_evolve_validates_resolved_persisted_budgets(
    tmp_path, monkeypatch, capsys, repeat_mode, budget_options,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    args.extend(("--evaluator-preparation-timeout", "7",
                 "--evaluator-preparation-wall-timeout", "80"))
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    parent = initial["run_id"]
    workspace = Path(initial["workspace"])
    before = snapshot(store, parent, workspace)
    mode = ["--multi-file"] if repeat_mode else []

    assert cli.main([
        "solve", "--resume", "--run-id", parent, "--evolve", *mode, *budget_options,
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "awaiting_input"
    assert resumed["evolution"]["preparation_budgets"] == initial["evolution"]["preparation_budgets"]
    assert snapshot(store, parent, workspace) == before
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls) == (1, 0, 0)
