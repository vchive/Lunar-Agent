import json
import shlex
import sys
from io import StringIO
from pathlib import Path

from famou.cli import _adapter_fingerprint, _portfolio_fingerprint, _runtime_fingerprint, main
from famou.store import Store


def _write_evolution_contract(path: Path, *, strategy: str = "loop", max_rounds: int = 2) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "problem_id": "cli-evolution",
                "problem_type": "routing",
                "statement": "Find a better route.",
                "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
                "decision_variables": ["route order"],
                "objective": {"name": "quality", "direction": "maximize"},
                "hard_constraints": [
                    {
                        "id": "serve-all",
                        "description": "Serve all items.",
                        "source": "user_confirmed",
                        "verification": "independent",
                    }
                ],
                "success_criteria": ["All items are served."],
                "deliverables": ["A route program."],
                "evolution": {
                    "strategy": strategy,
                    "max_rounds": max_rounds,
                    "stagnation_rounds": 10,
                },
            }
        ),
        encoding="utf-8",
    )


def test_adapter_fingerprint_is_canonical_and_profile_sensitive() -> None:
    command = ("/absolute/solver", "--json")
    first = _adapter_fingerprint(
        command,
        kind="generator",
        name="solver",
        role="solver",
        required_capabilities=("write_artifacts", "read_files"),
    )
    reordered = _adapter_fingerprint(
        command,
        kind="generator",
        name="solver",
        role="solver",
        required_capabilities=("read_files", "write_artifacts"),
    )
    changed_role = _adapter_fingerprint(
        command,
        kind="generator",
        name="solver",
        role="researcher",
        required_capabilities=("read_files", "write_artifacts"),
    )
    assert first == reordered
    assert first != changed_role
    assert first is not None and len(first) == 64

    portfolio = _portfolio_fingerprint(
        (command, ("/absolute/solver-b", "--json")),
        name="solver",
        role="solver",
        required_capabilities=("read_files",),
    )
    reversed_portfolio = _portfolio_fingerprint(
        (("/absolute/solver-b", "--json"), command),
        name="solver",
        role="solver",
        required_capabilities=("read_files",),
    )
    assert portfolio != reversed_portfolio

    one_shot = _runtime_fingerprint(
        "openai-compatible",
        endpoint="http://127.0.0.1:11434",
        model="local",
        name="solver",
        role="solver",
    )
    loop = _runtime_fingerprint(
        "openai-compatible",
        endpoint="http://127.0.0.1:11434",
        model="local",
        name="solver",
        role="solver",
        agent_loop=True,
        loop_max_steps=80,
        loop_allow_exec=True,
    )
    assert one_shot != loop


def _write_evolution_commands(root: Path) -> tuple[Path, Path]:
    generator = root / "generator.py"
    generator.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "iteration = request['iteration']\n"
        "print(json.dumps({'source': f'def solve():\\n    return {iteration}\\n'}))\n",
        encoding="utf-8",
    )
    evaluator = root / "evaluator.py"
    evaluator.write_text(
        "import json, pathlib, re, sys\n"
        "source = pathlib.Path(sys.argv[1]).read_text()\n"
        "score = float(re.search(r'return (\\d+)', source).group(1))\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'cli-fixture','validity':1,'quality':score,'combined_score':score,'detailed_scores':{'quality':{'value':score,'direction':'maximize'}},'error_info':[]}))\n",
        encoding="utf-8",
    )
    return generator, evaluator


def test_cli_run_and_status_use_repository_runtime(tmp_path: Path, capsys) -> None:
    assert main(["run", "cli goal", "--runtime", "mock", "--home", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    run_id = next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("run_id:"))

    assert main(["status", run_id, "--home", str(tmp_path)]) == 0
    status_output = capsys.readouterr().out
    assert "status: succeeded" in status_output


def test_cli_evolution_loop_options_require_openai_runtime(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-runtime",
                "mock",
                "--agent-runtime-loop",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 2
    )
    assert "openai-compatible" in capsys.readouterr().err


def test_cli_delegate_uses_explicit_absolute_command_and_returns_json(tmp_path: Path, capsys) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "pathlib.Path(request['workspace'], 'answer.md').write_text('evidence')\n"
        "print(json.dumps({'status':'succeeded','text':'delegated', 'artifacts':['answer.md'], 'metadata':{'source':'fixture'}}))\n",
        encoding="utf-8",
    )
    worker.chmod(worker.stat().st_mode | 0o100)
    home = tmp_path / "home"
    assert (
        main(
            [
                "delegate",
                "write an answer",
                "--agent-command",
                f"{sys.executable} {worker}",
                "--agent-name",
                "fixture",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["run_status"] == "succeeded"
    assert payload["adapter"] == "fixture"
    assert payload["artifacts"] == ["answer.md"]
    assert Path(payload["workspace"]).exists()
    assert main(["status", payload["run_id"], "--json", "--home", str(home)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["tasks"][0]["agent"]["adapter"] == "fixture"


def test_cli_delegate_detach_preserves_explicit_worker_request(tmp_path: Path, capsys, monkeypatch) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text("print('done')\n", encoding="utf-8")
    worker.chmod(worker.stat().st_mode | 0o100)
    calls = []

    class Process:
        pid = 43210

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    home = tmp_path / "home"
    assert (
        main(
            [
                "delegate",
                "long task",
                "--agent-command",
                f"{sys.executable} {worker}",
                "--detach",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"
    assert payload["detached"] is True
    assert calls and "--run-id" in calls[0][0]
    assert f"{sys.executable} {worker}" in calls[0][0]


def test_cli_evolve_loop_uses_sqlite_authority_and_resume_metadata(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path)
    generator, evaluator = _write_evolution_commands(tmp_path)
    generator_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(generator))}"
    evaluator_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(evaluator))}"

    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--generator-command",
                generator_command,
                "--evaluator-command",
                evaluator_command,
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["run_status"] == "succeeded"
    assert payload["evaluated_candidates"] == 2
    assert payload["best_score"] == 2.0
    run_id = payload["run_id"]

    assert main(["status", run_id, "--json", "--home", str(tmp_path / "home")]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["run"]["status"] == "succeeded"
    assert status["evolution"]["candidates"] == 2
    assert status["evolution"]["iterations"] == 2
    workspace = Path(payload["workspace"])
    assert (workspace / "evolution" / "archive.jsonl").is_file()
    assert (workspace / "evolution" / "state.json").is_file()
    assert (workspace / "evolution" / "result.json").is_file()

    assert main(["events", run_id, "--json", "--home", str(tmp_path / "home")]) == 0
    events = json.loads(capsys.readouterr().out)
    assert any(event["type"] == "evolution_started" for event in events)
    assert any(event["type"] == "evolution_iteration" for event in events)
    assert any(event["type"] == "evolution_finished" for event in events)


def test_cli_evolve_can_use_explicit_agent_as_candidate_generator(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(
        "import pathlib, re, sys, json\n"
        "source = pathlib.Path(sys.argv[1]).read_text()\n"
        "score = float(re.search(r'return (\\d+)', source).group(1))\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'agent-cli','validity':1,'quality':score,'combined_score':score,'detailed_scores':{'quality':{'value':score,'direction':'maximize'}},'error_info':[]}))\n",
        encoding="utf-8",
    )
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "print(json.dumps({'source':'def solve():\\n    return 9\\n','metadata':{'iteration':request['task_id']}}))\n",
        encoding="utf-8",
    )
    evaluator_command = f"{sys.executable} {evaluator}"
    agent_command = f"{sys.executable} {agent}"
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-command",
                agent_command,
                "--agent-capability",
                "read_files",
                "--evaluator-command",
                evaluator_command,
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["run_status"] == "succeeded"
    assert payload["best_score"] == 9.0


def test_cli_evolve_can_use_separate_evaluator_agent(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    solver = tmp_path / "solver.py"
    solver.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({'source':'def solve():\\n    return 3\\n'}))\n",
        encoding="utf-8",
    )
    evaluator = tmp_path / "evaluator-agent.py"
    evaluator.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "report = {'schema_version':'1','evaluator_id':'agent-evaluator','validity':1,'quality':3,'combined_score':3,'detailed_scores':{'quality':{'value':3,'direction':'maximize'}},'error_info':[]}\n"
        "print(json.dumps({'text': json.dumps(report)}))\n",
        encoding="utf-8",
    )
    solver.chmod(solver.stat().st_mode | 0o100)
    evaluator.chmod(evaluator.stat().st_mode | 0o100)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-command",
                f"{sys.executable} {solver}",
                "--evaluator-agent-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["best_score"] == 3.0
    assert payload["best_candidate_path"] == "evolution/candidates/candidate-0001/candidate.py"
    workspace = Path(payload["workspace"])
    assert (workspace / payload["best_candidate_path"]).is_file()
    assert main(["status", payload["run_id"], "--json", "--home", str(tmp_path / "home")]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["evolution"]["result"]["best_candidate_path"] == payload["best_candidate_path"]


def test_cli_evolve_accepts_solver_portfolio_and_rejects_conflicts(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, strategy="population", max_rounds=1)
    solver_a = tmp_path / "solver-a.py"
    solver_b = tmp_path / "solver-b.py"
    for path, value in ((solver_a, 2), (solver_b, 4)):
        path.write_text(
            "import json, sys\n"
            "json.loads(sys.stdin.read())\n"
            f"print(json.dumps({{'source':'def solve():\\n    return {value}\\n'}}))\n",
            encoding="utf-8",
        )
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(
        "import json, pathlib, re, sys\n"
        "source = pathlib.Path(sys.argv[1]).read_text()\n"
        "score = float(re.search(r'return (\\d+)', source).group(1))\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'portfolio','validity':1,'quality':score,'combined_score':score,'detailed_scores':{'quality':{'value':score,'direction':'maximize'}},'error_info':[]}))\n",
        encoding="utf-8",
    )
    command = [
        "evolve",
        str(contract_path),
        "--agent-portfolio-command",
        f"{sys.executable} {solver_a}",
        "--agent-portfolio-command",
        f"{sys.executable} {solver_b}",
        "--evaluator-command",
        f"{sys.executable} {evaluator}",
        "--population-size",
        "2",
        "--json",
        "--home",
        str(tmp_path / "home"),
    ]
    assert main(command) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    state = json.loads(
        (Path(payload["workspace"]) / "evolution" / "state.json").read_text(encoding="utf-8")
    )
    assert len(state["config"]["generator_fingerprint"]) == 64
    assert payload["best_score"] == 4.0
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-command",
                f"{sys.executable} {solver_a}",
                "--agent-portfolio-command",
                f"{sys.executable} {solver_b}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "conflict-home"),
            ]
        )
        == 2
    )
    assert "mutually exclusive" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_accepts_evaluator_portfolio_and_uses_median(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    solver = tmp_path / "solver.py"
    solver.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({'source':'def solve():\\n    return 5\\n'}))\n",
        encoding="utf-8",
    )
    evaluators = []
    for index, score in enumerate((1, 3), start=1):
        evaluator = tmp_path / f"evaluator-{index}.py"
        evaluator.write_text(
            "import json, sys\n"
            "json.loads(sys.stdin.read())\n"
            f"report = {{'schema_version':'1','evaluator_id':'agent-{index}','validity':1,"
            f"'quality':{score},'combined_score':{score},'detailed_scores':"
            f"{{'quality':{{'value':{score},'direction':'maximize'}}}},'error_info':[]}}\n"
            "print(json.dumps({'text': json.dumps(report)}))\n",
            encoding="utf-8",
        )
        solver.chmod(solver.stat().st_mode | 0o100)
        evaluator.chmod(evaluator.stat().st_mode | 0o100)
        evaluators.append(evaluator)
    home = tmp_path / "home"
    args = [
        "evolve",
        str(contract_path),
        "--agent-command",
        f"{sys.executable} {solver}",
        "--evaluator-portfolio-command",
        f"{sys.executable} {evaluators[0]}",
        "--evaluator-portfolio-command",
        f"{sys.executable} {evaluators[1]}",
        "--json",
        "--home",
        str(home),
    ]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["best_score"] == 2.0
    state = json.loads(
        (Path(payload["workspace"]) / "evolution" / "state.json").read_text(encoding="utf-8")
    )
    assert len(state["config"]["evaluator_fingerprint"]) == 64

    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-command",
                f"{sys.executable} {solver}",
                "--evaluator-portfolio-command",
                f"{sys.executable} {evaluators[0]}",
                "--evaluator-command",
                f"{sys.executable} {evaluators[0]}",
                "--json",
                "--home",
                str(tmp_path / "conflict-home"),
            ]
        )
        == 2
    )
    assert "mutually exclusive" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_rejects_single_evaluator_portfolio_and_openevolve_mix(
    tmp_path: Path, capsys
) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    solver, evaluator = _write_evolution_commands(tmp_path)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--generator-command",
                f"{sys.executable} {solver}",
                "--evaluator-portfolio-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "single-home"),
            ]
        )
        == 2
    )
    assert "at least two" in json.loads(capsys.readouterr().err)["error"]

    openevolve = tmp_path / "openevolve.py"
    openevolve.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    openevolve.chmod(openevolve.stat().st_mode | 0o100)
    openevolve_contract = tmp_path / "openevolve-contract.json"
    _write_evolution_contract(openevolve_contract, strategy="openevolve", max_rounds=1)
    assert (
        main(
            [
                "evolve",
                str(openevolve_contract),
                "--openevolve-command",
                str(openevolve),
                "--evaluator-portfolio-command",
                f"{sys.executable} {evaluator}",
                "--evaluator-portfolio-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "openevolve-home"),
            ]
        )
        == 2
    )
    assert "only supported" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_uses_repository_runtime_for_solver_and_evaluator(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    runtime = tmp_path / "runtime-agent.py"
    runtime.write_text(
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        "if 'independent evaluator' in prompt:\n"
        "    report = {'schema_version':'1','evaluator_id':'runtime','validity':1,"
        "'quality':6,'combined_score':6,'detailed_scores':{},'error_info':[]}\n"
        "    print(json.dumps(report))\n"
        "else:\n"
        "    print('def solve():\\n    return 6')\n",
        encoding="utf-8",
    )
    runtime.chmod(runtime.stat().st_mode | 0o100)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-runtime",
                "subprocess",
                "--agent-runtime-command",
                f"{sys.executable} {runtime}",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["best_score"] == 6.0
    state = json.loads(
        (Path(payload["workspace"]) / "evolution" / "state.json").read_text(encoding="utf-8")
    )
    assert len(state["config"]["generator_fingerprint"]) == 64
    assert len(state["config"]["evaluator_fingerprint"]) == 64
    assert "runtime-agent.py" not in json.dumps(state["config"])


def test_cli_benchmark_compares_native_strategies(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    workspace = tmp_path / "benchmark"

    assert (
        main(
            [
                "benchmark",
                str(contract_path),
                "--strategy",
                "loop",
                "--strategy",
                "population",
                "--generator-command",
                f"{sys.executable} {generator}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--max-rounds",
                "1",
                "--population-size",
                "2",
                "--json",
                "--workspace",
                str(workspace),
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert [item["strategy"] for item in payload["runs"]] == ["loop", "population"]
    assert all(item["best_score"] is not None for item in payload["runs"])
    assert str(generator) not in json.dumps(payload["config"])
    assert (workspace / "benchmark.json").is_file()


def test_cli_benchmark_includes_explicit_openevolve(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    wrapper = tmp_path / "openevolve-wrapper.py"
    wrapper.write_text(
        "import json, pathlib, sys\n"
        "config_path = pathlib.Path(sys.argv[-1])\n"
        "config = json.loads(config_path.read_text())\n"
        "assert config['budget']['max_rounds'] == 1\n"
        "root = config_path.parent\n"
        "(root / 'candidate.py').write_text('def solve():\\n    return 7\\n')\n"
        "(root / 'result.json').write_text(json.dumps({'candidate_path':'candidate.py'}))\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "benchmark-openevolve"
    assert (
        main(
            [
                "benchmark",
                str(contract_path),
                "--strategy",
                "loop",
                "--strategy",
                "openevolve",
                "--generator-command",
                f"{sys.executable} {generator}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--openevolve-command",
                f"{sys.executable} {wrapper}",
                "--max-rounds",
                "1",
                "--population-size",
                "2",
                "--json",
                "--workspace",
                str(workspace),
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert [item["strategy"] for item in payload["runs"]] == ["loop", "openevolve"]
    assert all(item["status"] == "completed" for item in payload["runs"])
    assert "openevolve" in payload["config"]["strategy_commands_sha256"]


def test_cli_evolve_runtime_can_fill_one_role_and_rejects_unused_profile(
    tmp_path: Path, capsys
) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    runtime = tmp_path / "runtime-agent.py"
    runtime.write_text(
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        "if 'independent evaluator' in prompt:\n"
        "    print(json.dumps({'schema_version':'1','evaluator_id':'runtime','validity':1,"
        "'quality':2,'combined_score':2,'detailed_scores':{},'error_info':[]}))\n"
        "else:\n"
        "    print(json.dumps({'source':'def solve():\\n    return 2'}))\n",
        encoding="utf-8",
    )
    runtime.chmod(runtime.stat().st_mode | 0o100)
    _, evaluator = _write_evolution_commands(tmp_path)
    solver = tmp_path / "solver.py"
    solver.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({'source':'def solve():\\n    return 2'}))\n",
        encoding="utf-8",
    )
    solver.chmod(solver.stat().st_mode | 0o100)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-runtime",
                "subprocess",
                "--agent-runtime-command",
                f"{sys.executable} {runtime}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "mixed-home"),
            ]
        )
        == 0
    )
    mixed = json.loads(capsys.readouterr().out)
    assert mixed["best_score"] == 2.0
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-runtime",
                "subprocess",
                "--agent-runtime-command",
                f"{sys.executable} {runtime}",
                "--agent-command",
                f"{sys.executable} {solver}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(tmp_path / "unused-home"),
            ]
        )
        == 2
    )
    assert "unused" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_detach_propagates_runtime_without_secret_argv(tmp_path: Path, capsys, monkeypatch) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    runtime = tmp_path / "runtime-agent.py"
    runtime.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    runtime.chmod(runtime.stat().st_mode | 0o100)
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--agent-runtime",
                "openai-compatible",
                "--agent-runtime-endpoint",
                "http://127.0.0.1:1234/v1/chat/completions",
                "--agent-runtime-model",
                "fixture-model",
                "--agent-runtime-api-key",
                "secret-runtime-key",
                "--detach",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    child_command, child_kwargs = calls[0]
    assert "--agent-runtime" in child_command
    assert "secret-runtime-key" not in child_command
    assert child_kwargs["env"]["FAMOU_AGENT_RUNTIME_API_KEY"] == "secret-runtime-key"


def test_cli_evolve_execution_backed_evaluator_indexes_evidence_and_provenance(
    tmp_path: Path, capsys
) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, _ = _write_evolution_commands(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import pathlib, sys\n"
        "candidate = pathlib.Path(sys.argv[1])\n"
        "assert candidate.is_file()\n"
        "pathlib.Path('runner-output.txt').write_text('ok')\n"
        "pathlib.Path('execution-artifacts.json').write_text('[\"runner-output.txt\"]')\n"
        "print('executed')\n",
        encoding="utf-8",
    )
    evaluator = tmp_path / "execution-evaluator.py"
    evaluator.write_text(
        "import json, pathlib, sys\n"
        "candidate = pathlib.Path(sys.argv[1])\n"
        "evidence = json.loads((candidate.parent / 'execution.json').read_text())\n"
        "score = 8 if evidence['status'] == 'succeeded' else 0\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'exec-fixture','validity':"
        "1 if score else 0,'quality':score if score else None,'combined_score':score,"
        "'detailed_scores':{},'error_info':[] if score else [{'code':'execution',"
        "'message':'candidate did not execute'}]}))\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--generator-command",
                f"{sys.executable} {generator}",
                "--candidate-runner-command",
                f"{sys.executable} {runner}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["best_score"] == 8.0
    workspace = Path(payload["workspace"])
    evidence = workspace / "evolution" / "candidates" / "candidate-0001" / "execution.json"
    assert evidence.is_file()
    artifacts = Store(home / "state.db").list_artifacts(payload["run_id"])
    assert any(item["path"].endswith("/execution.json") and item["kind"] == "candidate_execution" for item in artifacts)
    assert any(
        item["path"].endswith("/runner-output.txt")
        and item["kind"] == "candidate_execution_output"
        for item in artifacts
    )
    state = json.loads((workspace / "evolution" / "state.json").read_text(encoding="utf-8"))
    assert len(state["config"]["runner_fingerprint"]) == 64
    assert str(runner) not in json.dumps(state["config"])


def test_cli_evolve_runner_requires_legacy_evaluator_command(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    runner = tmp_path / "runner.py"
    runner.write_text("import sys\n", encoding="utf-8")
    runner.chmod(runner.stat().st_mode | 0o100)

    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--candidate-runner-command",
                f"{sys.executable} {runner}",
                "--agent-runtime",
                "mock",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 2
    )
    assert "requires --evaluator-command" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_detach_propagates_candidate_runner(tmp_path: Path, capsys, monkeypatch) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text("import sys\n", encoding="utf-8")
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--generator-command",
                f"{sys.executable} {generator}",
                "--candidate-runner-command",
                f"{sys.executable} {runner}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--detach",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    child_command = calls[0][0]
    assert "--candidate-runner-command" in child_command
    assert f"{sys.executable} {runner}" in child_command


def test_cli_evolve_resume_rejects_changed_runner_provenance(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text("print('ok')\n", encoding="utf-8")
    home = tmp_path / "home"
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--generator-command",
                f"{sys.executable} {generator}",
                "--candidate-runner-command",
                f"{sys.executable} {runner}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    changed_runner = tmp_path / "changed-runner.py"
    changed_runner.write_text("print('changed')\n", encoding="utf-8")
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--resume",
                "--run-id",
                run_id,
                "--generator-command",
                f"{sys.executable} {generator}",
                "--candidate-runner-command",
                f"{sys.executable} {changed_runner}",
                "--evaluator-command",
                f"{sys.executable} {evaluator}",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 2
    )
    assert "configuration does not match" in json.loads(capsys.readouterr().err)["error"]


def test_cli_evolve_requires_explicit_commands_and_supports_population(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, strategy="population", max_rounds=1)
    assert main(["evolve", str(contract_path), "--json", "--home", str(tmp_path / "home")]) == 2
    assert "generator-command" in json.loads(capsys.readouterr().err)["error"]
    generator, evaluator = _write_evolution_commands(tmp_path)
    command_args = [
        "evolve",
        str(contract_path),
        "--generator-command",
        f"{sys.executable} {generator}",
        "--evaluator-command",
        f"{sys.executable} {evaluator}",
        "--population-size",
        "2",
        "--offspring-per-iteration",
        "1",
        "--json",
        "--home",
        str(tmp_path / "home"),
    ]
    assert main(command_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["strategy"] == "population"
    assert payload["run_status"] == "succeeded"


def test_cli_evolve_detach_returns_handle_then_resume_executes_same_run(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    command_args = [
        "evolve",
        str(contract_path),
        "--generator-command",
        f"{sys.executable} {generator}",
        "--evaluator-command",
        f"{sys.executable} {evaluator}",
        "--detach",
        "--json",
        "--home",
        str(tmp_path / "home"),
    ]
    assert main(command_args) == 0
    detached = json.loads(capsys.readouterr().out)
    assert detached["status"] == "pending" and detached["detached"] is True
    assert calls and "--resume" in calls[0][0]
    monkeypatch.undo()

    resume_args = [
        "evolve",
        str(contract_path),
        "--resume",
        "--run-id",
        detached["run_id"],
        "--generator-command",
        f"{sys.executable} {generator}",
        "--evaluator-command",
        f"{sys.executable} {evaluator}",
        "--json",
        "--home",
        str(tmp_path / "home"),
    ]
    assert main(resume_args) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["run_id"] == detached["run_id"]
    assert resumed["run_status"] == "succeeded"


def test_cli_evolve_resume_rejects_changed_evaluator_command(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    generator, evaluator = _write_evolution_commands(tmp_path)
    home = tmp_path / "home"
    command_args = [
        "evolve",
        str(contract_path),
        "--generator-command",
        f"{sys.executable} {generator}",
        "--evaluator-command",
        f"{sys.executable} {evaluator}",
        "--json",
        "--home",
        str(home),
    ]
    assert main(command_args) == 0
    first = json.loads(capsys.readouterr().out)
    state = json.loads(
        (Path(first["workspace"]) / "evolution" / "state.json").read_text(encoding="utf-8")
    )
    assert len(state["config"]["generator_fingerprint"]) == 64
    assert len(state["config"]["evaluator_fingerprint"]) == 64
    changed_evaluator = tmp_path / "evaluator-changed.py"
    changed_evaluator.write_text(evaluator.read_text(encoding="utf-8"), encoding="utf-8")
    changed_evaluator.chmod(evaluator.stat().st_mode)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--resume",
                "--run-id",
                first["run_id"],
                "--generator-command",
                f"{sys.executable} {generator}",
                "--evaluator-command",
                f"{sys.executable} {changed_evaluator}",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "configuration does not match" in error["error"]


def test_cli_evolve_openevolve_is_explicit_and_imports_canonical_result(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, strategy="openevolve", max_rounds=1)
    external = tmp_path / "openevolve.py"
    external.write_text(
        "import json, pathlib, sys\n"
        "config = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "root = pathlib.Path.cwd()\n"
        "(root / 'candidate.py').write_text('def solve():\\n    return 7\\n')\n"
        "(root / 'result.json').write_text(json.dumps({'candidate_path':'candidate.py','evaluation':{'schema_version':'1','evaluator_id':'external','validity':1,'quality':0.7,'combined_score':0.7,'detailed_scores':{'quality':{'value':0.7,'direction':'maximize'}},'error_info':[]}}))\n",
        encoding="utf-8",
    )
    external.chmod(external.stat().st_mode | 0o100)
    assert (
        main(
            [
                "evolve",
                str(contract_path),
                "--openevolve-command",
                f"{sys.executable} {external}",
                "--json",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["strategy"] == "openevolve"
    assert payload["best_score"] == 0.7
    assert payload["run_status"] == "succeeded"


def test_cli_json_contract_and_stdin_goal(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("stdin goal"))
    assert main(["run", "-", "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["status"] == "succeeded"

    assert main(["status", run_payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["run"]["goal"] == "stdin goal"
    assert status_payload["tasks"][0]["state"] == "succeeded"
    assert status_payload["tasks"][0]["evaluation"]["details"]["kind"] == "non_empty"

    assert main(["events", run_payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    events = json.loads(capsys.readouterr().out)
    evaluation = next(event for event in events if event["type"] == "task_evaluated")
    assert evaluation["payload"]["details"]["kind"] == "non_empty"


def test_cli_status_json_exposes_route_profiles_and_budget(tmp_path: Path, capsys) -> None:
    assert main(["run", "analyze this CSV", "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["route"]["domain"] == "data"
    assert status["run"]["evaluator_profile"] == "data"
    assert status["budget"]["max_tool_steps"] == 40


def test_cli_status_json_exposes_algorithm_contract_and_manifest(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "algorithm-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "solve routing",
                "plan_id": "algorithm-cli-plan",
                "tasks": [{"id": "solve", "title": "Solve", "prompt": "write result"}],
                "algorithm_problem": {
                    "problem_id": "routing-cli",
                    "problem_type": "routing",
                    "statement": "Assign every item to a route.",
                    "inputs": [
                        {
                            "path": "items.csv",
                            "format": "csv",
                            "fields": {"item_id": "unique item identifier"},
                            "key": "item_id",
                        }
                    ],
                    "decision_variables": ["route per item"],
                    "objective": {"name": "travel time", "direction": "minimize"},
                    "hard_constraints": [
                        {
                            "id": "serve-each",
                            "description": "Serve every item once.",
                            "source": "user_confirmed",
                            "verification": "independent",
                            "result_fields": ["item_id"],
                        }
                    ],
                    "success_criteria": ["Every item appears."],
                    "deliverables": ["Route table."],
                },
            }
        ),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["algorithm_problem"]["problem_type"] == "routing"
    assert status["algorithm_workspace"]["kind"] == "algorithm_manifest"
    assert (Path(status["run"]["workspace"]) / "algorithm-workspace.json").is_file()


def test_cli_recover_persists_an_advisory_proposal_in_status(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "recovery-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "write a checked report",
                "plan_id": "cli-recovery-plan",
                "tasks": [
                    {
                        "id": "report",
                        "title": "Report",
                        "prompt": "write report.json",
                        "acceptance": {"artifact_exists": "report.json"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 1
    run_id = json.loads(capsys.readouterr().out)["run_id"]

    assert main(["recover", run_id, "--json", "--home", str(tmp_path)]) == 0
    recovery = json.loads(capsys.readouterr().out)
    assert recovery["proposal"]["action"] == "propose_patch"

    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["recovery"] == recovery["proposal"]


def test_cli_detach_returns_durable_handle_before_execution(tmp_path: Path, capsys, monkeypatch) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "long goal",
                "--runtime",
                "mock",
                "--detach",
                "--workers",
                "3",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"
    assert payload["workers"] == 3
    assert payload["run_id"]
    assert calls[0][0][:4] == [sys.executable, "-m", "famou", "resume"]
    assert calls[0][0][calls[0][0].index("--workers") + 1] == "3"
    assert calls[0][1]["start_new_session"] is True

    assert main(["status", payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["run"]["status"] == "pending"


def test_cli_accepts_json_plan_and_rejects_malformed_plan(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "cli plan",
                "tasks": [
                    {"id": "one", "prompt": "one"},
                    {"id": "two", "prompt": "two", "depends_on": ["one"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["run", "--plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(
        '{"goal":"bad","tasks":[{"id":"a","prompt":"a","depends_on":["a"]}]}',
        encoding="utf-8",
    )
    assert main(["run", "--plan", str(bad_path), "--json", "--home", str(tmp_path / "bad-home")]) == 2
    assert "depend" in capsys.readouterr().err


def test_cli_workers_option_is_additive_and_runs_parallel_plan(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "parallel.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "parallel cli plan",
                "tasks": [
                    {"id": "one", "prompt": "one"},
                    {"id": "two", "prompt": "two"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "run",
                "--plan",
                str(plan_path),
                "--runtime",
                "mock",
                "--workers",
                "2",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["workers"] == 2


def test_cli_rejects_non_positive_workers_before_execution(tmp_path: Path, capsys) -> None:
    assert main(["run", "goal", "--workers", "0", "--json", "--home", str(tmp_path)]) == 2
    assert "max_workers" in capsys.readouterr().err


def test_detached_model_options_propagate_without_api_key_in_argv(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "model goal",
                "--runtime",
                "openai-compatible",
                "--endpoint",
                "http://127.0.0.1:1234/v1",
                "--model",
                "fixture",
                "--api-key",
                "secret-key",
                "--detach",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    command, kwargs = calls[0]
    assert "--endpoint" in command and "--model" in command
    assert "--api-key" not in command
    assert kwargs["env"]["FAMOU_API_KEY"] == "secret-key"


def test_detached_agent_loop_options_propagate(tmp_path: Path, capsys, monkeypatch) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "long model goal",
                "--runtime",
                "openai-compatible",
                "--endpoint",
                "http://127.0.0.1:1234/v1",
                "--model",
                "fixture",
                "--agent-loop",
                "--max-steps",
                "7",
                "--allow-exec",
                "--memory",
                "--session-history",
                "--detach",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    command = calls[0][0]
    assert "--agent-loop" in command
    assert command[command.index("--max-steps") + 1] == "7"
    assert "--allow-exec" in command and "--memory" in command
    assert "--session-history" in command


def test_cli_memory_inspection_is_json(tmp_path: Path, capsys) -> None:
    from famou.memory import MemoryStore

    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    memory.remember("remembered deployment decision", source="test")
    assert main(["memory", "deployment", "--json", "--home", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["content"] == "remembered deployment decision"


def test_cli_master_decide_and_plan_revision_commands(tmp_path: Path, capsys) -> None:
    assert main(["decide", "What is SQLite WAL?", "--json", "--home", str(tmp_path)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["action"] == "answer"
    assert "plan" not in decision

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "create a report and verify it",
                "plan_id": "plan-cli",
                "tasks": [{"id": "one", "title": "One", "prompt": "write one"}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["plan_version"] == 1
    run_id = created["run_id"]

    assert main(["plan", run_id, "--json", "--home", str(tmp_path)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["plan_id"] == "plan-cli"
    assert inspected["version"] == 1

    patch_path = tmp_path / "patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "plan_id": "plan-cli",
                "base_version": 1,
                "reason": "add verification",
                "operations": [
                    {"op": "add_task", "task": {"id": "check", "prompt": "verify output", "depends_on": ["one"]}}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["patch", run_id, str(patch_path), "--json", "--home", str(tmp_path)]) == 0
    patched = json.loads(capsys.readouterr().out)
    assert patched["plan_version"] == 2

    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["run"]["current_plan_version"] == 2
    assert status["tasks"][0]["plan_task_id"] == "one"


def test_cli_replan_inherits_plan_id_and_stale_patch_is_json_error(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"goal": "replan me", "plan_id": "plan-replan", "tasks": [{"id": "one", "prompt": "one"}]}),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--json", "--home", str(tmp_path)]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    replacement = tmp_path / "replacement.json"
    replacement.write_text(
        json.dumps({"goal": "replan me better", "tasks": [{"id": "one", "prompt": "one"}]}),
        encoding="utf-8",
    )
    assert main(["replan", run_id, str(replacement), "--json", "--home", str(tmp_path)]) == 0
    replanned = json.loads(capsys.readouterr().out)
    assert replanned["plan_id"] == "plan-replan" and replanned["plan_version"] == 2

    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps(
            {
                "plan_id": "plan-replan",
                "base_version": 1,
                "reason": "stale",
                "operations": [{"op": "update_task", "id": "one", "prompt": "old"}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["patch", run_id, str(stale), "--json", "--home", str(tmp_path)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "does not match" in error["error"]


def test_cli_deliver_rejects_failed_run(tmp_path: Path, capsys) -> None:
    # An unknown/failed handle must return a machine-readable error rather than a deliver decision.
    assert main(["deliver", "missing-run", "--json", "--home", str(tmp_path)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "unknown run" in error["error"]
