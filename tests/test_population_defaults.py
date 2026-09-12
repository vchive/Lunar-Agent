"""Cross-entry-point regression checks for the population-first default.

These tests deliberately compare an omitted strategy with an explicit ``population`` request.
The commands use deterministic local fixtures, so the check covers the contract compiler,
conversational solve handoff, standalone evolution, and benchmark construction without invoking a
model, provider, or external evolution framework.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.cli import main
from famou.conversational import RuntimeContractCompiler, build_algorithm_plan
from famou.runtime import MockRuntime


def _contract_payload() -> dict[str, object]:
    """Return a valid contract with the evolution strategy intentionally omitted."""

    return {
        "schema_version": "1",
        "problem_id": "population-default-fixture",
        "problem_type": "routing",
        "statement": "Find a bounded deterministic route.",
        "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
        "decision_variables": ["route order"],
        "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [],
        "soft_constraints": [],
        "success_criteria": ["Every item is served."],
        "deliverables": ["route source"],
    }


def _write_contract(path: Path) -> AlgorithmProblemContract:
    payload = _contract_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return AlgorithmProblemContract.from_dict(payload)


def _write_command_fixtures(root: Path) -> tuple[Path, Path]:
    generator = root / "generator.py"
    generator.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(pathlib.Path(sys.argv[-1]).read_text())\n"
        "value = int(request['iteration']) + len(request['archive'])\n"
        "print(json.dumps({'source': f'def solve():\\n    return {value}\\n'}))\n",
        encoding="utf-8",
    )
    evaluator = root / "evaluator.py"
    evaluator.write_text(
        "import json\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'population-default-fixture',"
        "'validity':1,'quality':1,'combined_score':1,'detailed_scores':{},'error_info':[]}))\n",
        encoding="utf-8",
    )
    return generator, evaluator


def _command(path: Path) -> str:
    return shlex.join((sys.executable, str(path)))


def _state_for(result: dict[str, object]) -> dict[str, object]:
    workspace = Path(result["workspace"])
    return json.loads((workspace / "evolution" / "state.json").read_text(encoding="utf-8"))


def test_contract_compiler_and_plan_materialize_population_by_default(tmp_path: Path) -> None:
    omitted = AlgorithmProblemContract.from_dict(_contract_payload())
    assert omitted.evolution.strategy == "population"

    compiled = RuntimeContractCompiler(MockRuntime()).compile(
        "optimize a deterministic route",
        tmp_path,
    )
    assert compiled.contract is not None
    assert compiled.contract.evolution.strategy == "population"

    plan = build_algorithm_plan("optimize a deterministic route", omitted)
    assert plan.algorithm_problem is not None
    assert plan.algorithm_problem["evolution"]["strategy"] == "population"

    explicit = AlgorithmProblemContract.from_dict(
        {
            **omitted.to_dict(),
            "evolution": {
                "strategy": "population",
                "max_rounds": omitted.evolution.max_rounds,
                "stagnation_rounds": omitted.evolution.stagnation_rounds,
            },
        }
    )
    assert explicit.evolution.strategy == omitted.evolution.strategy
    assert explicit.digest() == omitted.digest()


def test_solve_evolve_omitted_strategy_matches_explicit_population(
    tmp_path: Path, capsys
) -> None:
    def run(home: Path, explicit: bool) -> tuple[dict[str, object], dict[str, object]]:
        args = [
            "solve",
            "optimize a deterministic route",
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--home",
            str(home),
        ]
        if explicit:
            args[args.index("--evolve") + 1 : args.index("--max-rounds")] = [
                "--strategy",
                "population",
            ]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        payload = json.loads(output.out)
        return payload, _state_for(payload["evolution"])

    omitted, omitted_state = run(tmp_path / "solve-omitted", False)
    explicit, explicit_state = run(tmp_path / "solve-explicit", True)

    assert omitted["evolution"]["strategy"] == explicit["evolution"]["strategy"] == "population"
    assert omitted["compiler"]["contract_sha256"] == explicit["compiler"]["contract_sha256"]
    assert omitted_state["config"] == explicit_state["config"]
    assert omitted_state["strategy"] == explicit_state["strategy"] == "population"


def test_standalone_evolve_omitted_strategy_matches_explicit_population(
    tmp_path: Path, capsys
) -> None:
    contract_path = tmp_path / "contract.json"
    contract = _write_contract(contract_path)
    generator, evaluator = _write_command_fixtures(tmp_path)

    def run(home: Path, explicit: bool) -> tuple[dict[str, object], dict[str, object]]:
        args = [
            "evolve",
            str(contract_path),
            "--generator-command",
            _command(generator),
            "--evaluator-command",
            _command(evaluator),
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--home",
            str(home),
        ]
        if explicit:
            args[2:2] = ["--strategy", "population"]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        payload = json.loads(output.out)
        return payload, _state_for(payload)

    omitted, omitted_state = run(tmp_path / "evolve-omitted", False)
    explicit, explicit_state = run(tmp_path / "evolve-explicit", True)

    assert omitted["strategy"] == explicit["strategy"] == "population"
    assert omitted["contract_sha256"] == explicit["contract_sha256"] == contract.digest()
    assert omitted_state["config"] == explicit_state["config"]
    assert omitted_state["strategy"] == explicit_state["strategy"] == "population"


def test_benchmark_omitted_strategy_matches_explicit_population(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    contract = _write_contract(contract_path)
    generator, evaluator = _write_command_fixtures(tmp_path)

    def run(workspace: Path, explicit: bool) -> dict[str, object]:
        args = [
            "benchmark",
            str(contract_path),
            "--generator-command",
            _command(generator),
            "--evaluator-command",
            _command(evaluator),
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--workspace",
            str(workspace),
            "--home",
            str(workspace.parent / "home"),
        ]
        if explicit:
            args[2:2] = ["--strategy", "population"]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        return json.loads(output.out)

    omitted = run(tmp_path / "benchmark-omitted", False)
    explicit = run(tmp_path / "benchmark-explicit", True)

    assert omitted["contract_sha256"] == explicit["contract_sha256"] == contract.digest()
    assert omitted["config"] == explicit["config"]
    assert omitted["config"]["strategies"] == ["population"]
    assert [item["strategy"] for item in omitted["runs"]] == ["population"]
    assert [item["strategy"] for item in explicit["runs"]] == ["population"]
