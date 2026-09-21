"""The automatic solve wall policy is explicit, immutable, and legacy-safe."""
from __future__ import annotations

import json

import pytest

from lunar_evolution import cli
from lunar_evolution.evolution import EvolutionError


def automatic_request(*extra: str) -> dict[str, object]:
    args = cli.build_parser().parse_args([
        "solve", "optimize", "--evolve", "--multi-file", *extra,
    ])
    cli._prepare_conversational_bundle(args)
    return cli._evolution_request_payload(args)


def test_automatic_request_persists_only_explicit_solve_policy() -> None:
    omitted = automatic_request()
    assert omitted["automatic_lifecycle_version"] == 1
    assert "solve_wall_timeout" not in omitted
    assert "solve_wall_timeout_source" not in omitted

    explicit = automatic_request("--solve-wall-timeout", "45")
    assert explicit["automatic_lifecycle_version"] == 1
    assert explicit["solve_wall_timeout"] == 45.0
    assert explicit["solve_wall_timeout_source"] == "explicit"


@pytest.mark.parametrize("value", ["0", "-1", "86401", "nan", "inf"])
def test_invalid_solve_wall_timeout_is_rejected_before_database(
    tmp_path, monkeypatch, capsys, value: str,
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("invalid solve wall policy must not construct a runtime")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main([
        "solve", "optimize", "--evolve", "--multi-file",
        "--solve-wall-timeout", value,
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "solve-wall-timeout" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home" / "state.db").exists()


@pytest.mark.parametrize("arguments", [
    ["solve", "optimize", "--solve-wall-timeout", "45"],
    ["solve", "optimize", "--evolve", "--solve-wall-timeout", "45"],
])
def test_solve_wall_timeout_requires_native_automatic_mode(
    tmp_path, monkeypatch, capsys, arguments: list[str],
) -> None:
    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: pytest.fail("runtime constructed"))
    assert cli.main([*arguments, "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "solve-wall-timeout" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home" / "state.db").exists()


def test_continuation_restores_exact_policy_and_rejects_mismatch() -> None:
    request = automatic_request("--solve-wall-timeout", "45")
    parser = cli.build_parser()
    omitted = parser.parse_args(["resume", "parent"])
    cli._validate_conversational_bundle_request(omitted, request)
    cli._validate_evolution_override(omitted, request)
    restored = cli._evolution_args(omitted, request)
    assert restored.solve_wall_timeout == 45.0

    mismatch = parser.parse_args(["resume", "parent", "--solve-wall-timeout", "46"])
    with pytest.raises(EvolutionError, match="solve_wall_timeout"):
        cli._validate_conversational_bundle_request(mismatch, request)


def test_legacy_automatic_handoff_cannot_acquire_new_policy() -> None:
    request = automatic_request()
    request.pop("automatic_lifecycle_version")
    parser = cli.build_parser()
    supplied = parser.parse_args(["resume", "parent", "--solve-wall-timeout", "45"])
    with pytest.raises(EvolutionError, match="legacy handoff"):
        cli._validate_conversational_bundle_request(supplied, request)

    omitted = parser.parse_args(["resume", "parent"])
    cli._validate_conversational_bundle_request(omitted, request)
    assert cli._evolution_args(omitted, request).solve_wall_timeout is None


def test_solve_policy_without_lifecycle_marker_is_invalid() -> None:
    request = automatic_request("--solve-wall-timeout", "45")
    request.pop("automatic_lifecycle_version")
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match="lifecycle marker"):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("mutation", [
    {"automatic_lifecycle_version": 2},
    {"solve_wall_timeout": 45.0},
    {"solve_wall_timeout": 45.0, "solve_wall_timeout_source": "default"},
])
def test_malformed_persisted_solve_policy_is_rejected(mutation: dict[str, object]) -> None:
    persisted = automatic_request()
    persisted.update(mutation)
    args = cli.build_parser().parse_args(["resume", "parent"])
    with pytest.raises(EvolutionError, match="solve_wall_timeout|lifecycle marker"):
        cli._validate_conversational_bundle_request(args, persisted)
