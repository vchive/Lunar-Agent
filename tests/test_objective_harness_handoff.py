import json
import sys
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.cli import main
from famou.runtime import RuntimeResult
from famou.store import Store


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "objective-harness-routes",
            "problem_type": "routing",
            "statement": "Assign every observed order and minimize route cost.",
            "inputs": [
                {"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is assigned."],
            "deliverables": ["route table"],
            "outputs": [
                {
                    "path": "output/routes.csv",
                    "format": "csv",
                    "fields": ["item_id", "route_id", "cost"],
                    "required": True,
                }
            ],
            "evolution": {"strategy": "loop", "max_rounds": 2, "stagnation_rounds": 3},
        }
    )


class HarnessRuntime:
    name = "objective-harness-runtime"

    def __init__(self) -> None:
        self.generation_calls = 0
        self.evaluation_calls = 0

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del workspace, timeout
        if "algorithm contract compiler" in prompt:
            return RuntimeResult(json.dumps({"status": "compiled", "contract": _contract().to_dict()}))
        if "solver in a bounded local algorithm-evolution run" in prompt:
            self.generation_calls += 1
            cost = 90 if self.generation_calls == 1 else 10
            return RuntimeResult(
                "from pathlib import Path\n"
                "rows = Path('data/raw/orders.csv').read_text().splitlines()[1:]\n"
                "Path('output').mkdir(exist_ok=True)\n"
                f"cost = {cost}\n"
                "body = 'item_id,route_id,cost\\n' + ''.join(f'{row},route-a,{cost}\\n' for row in rows)\n"
                "Path('output/routes.csv').write_text(body)\n"
            )
        if "Return exactly one JSON EvaluationReport object" in prompt:
            self.evaluation_calls += 1
            return RuntimeResult(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "wrong-model-evaluator",
                        "validity": 1,
                        "quality": 999,
                        "combined_score": 999,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                )
            )
        raise AssertionError("unexpected runtime prompt")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[None, None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


class QuestionHarnessRuntime(HarnessRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.compilation_calls = 0

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        if "algorithm contract compiler" in prompt:
            self.compilation_calls += 1
            if self.compilation_calls == 1:
                return RuntimeResult(
                    json.dumps(
                        {
                            "status": "needs_input",
                            "questions": [
                                {"question": "Which objective?", "options": ["cost", "time"]}
                            ],
                        }
                    )
                )
        return super().run(prompt, workspace, timeout)


def _write_harness(tmp_path: Path) -> Path:
    harness = tmp_path / "score.py"
    harness.write_text(
        "import csv, json, os, pathlib, sys, traceback\n"
        "candidate = pathlib.Path(sys.argv[1])\n"
        "root = candidate.parent\n"
        "try:\n"
        " assert 'FAMOU_API_KEY' not in os.environ\n"
        " assert 'LUNAR_HARNESS_SENTINEL' not in os.environ\n"
        " assert json.loads((root / 'execution.json').read_text())['status'] == 'succeeded'\n"
        " assert (root / 'data/raw/orders.csv').read_text().splitlines()[1] == 'secret-order-42'\n"
        " cost = float(next(csv.DictReader((root / 'output/routes.csv').open()))['cost'])\n"
        " utility = 1 / (1 + cost)\n"
        " print(json.dumps({'schema_version':'1','evaluator_id':'exact-cost','validity':1,"
        "'quality':utility,'combined_score':utility,'detailed_scores':"
        "{'cost':{'value':cost,'direction':'minimize'}},'error_info':[]}))\n"
        "except Exception:\n"
        " traceback.print_exc()\n"
        " raise\n",
        encoding="utf-8",
    )
    return harness


def test_solve_evolve_uses_exact_harness_and_materializes_its_winner(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = HarnessRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setenv("FAMOU_API_KEY", "sk-model-secret-must-not-reach-harness")
    monkeypatch.setenv("LUNAR_HARNESS_SENTINEL", "must-not-reach-harness")
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nsecret-order-42\n", encoding="utf-8")
    harness = _write_harness(tmp_path)
    home = tmp_path / "home"
    command = f"{sys.executable} {harness}"

    assert (
        main(
            [
                "solve",
                "minimize route cost and return routes.csv",
                "--runtime",
                "mock",
                "--input",
                str(orders),
                "--evolve",
                "--max-rounds",
                "2",
                "--stagnation-rounds",
                "3",
                "--evaluator-command",
                command,
                "--timeout",
                "2",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    child = Path(payload["evolution"]["workspace"])
    archive = [
        json.loads(line)
        for line in (child / "evolution" / "archive.jsonl").read_text().splitlines()
    ]

    assert runtime.evaluation_calls == 0
    assert [item["evaluation"]["combined_score"] for item in archive] == [1 / 91, 1 / 11]
    assert payload["evolution"]["result"]["best_candidate_id"] == "candidate-0002"
    assert (Path(payload["workspace"]) / "output" / "routes.csv").read_text().endswith(
        "secret-order-42,route-a,10\n"
    )
    request = next(
        event["payload"]
        for event in Store(home / "state.db").list_events(payload["run_id"])
        if event["type"] == "evolution_requested"
    )
    assert request["evaluator_command_configured"] is True
    assert str(harness) not in json.dumps(request)
    assert str(harness) not in (child / "evolution" / "state.json").read_text()

    assert (
        main(
            [
                "solve",
                "--resume",
                "--run-id",
                payload["run_id"],
                "--runtime",
                "mock",
                "--evolve",
                "--max-rounds",
                "2",
                "--stagnation-rounds",
                "3",
                "--evaluator-command",
                command,
                "--timeout",
                "2",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["evolution"]["run_id"] == payload["evolution"]["run_id"]


def test_harness_configuration_requires_native_evolution_and_matching_resume(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = HarnessRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    harness = _write_harness(tmp_path)
    command = f"{sys.executable} {harness}"
    home = tmp_path / "home"

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--evaluator-command",
            command,
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "require --evolve" in capsys.readouterr().err

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--evolve",
            "--strategy",
            "openevolve",
            "--evaluator-command",
            command,
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "native" in capsys.readouterr().err

    orders = tmp_path / "orders.csv"
    orders.write_text("id\nsecret-order-42\n", encoding="utf-8")
    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--input",
            str(orders),
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--evaluator-command",
            command,
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    first = json.loads(capsys.readouterr().out)

    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            first["run_id"],
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "evaluator command" in capsys.readouterr().err

    other = tmp_path / "other.py"
    other.write_text(harness.read_text(), encoding="utf-8")
    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            first["run_id"],
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--evaluator-command",
            f"{sys.executable} {other}",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "do not match" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["malformed", "nonzero", "timeout"])
def test_invalid_objective_harness_output_fails_closed(
    tmp_path: Path, capsys, monkeypatch, mode: str
) -> None:
    runtime = HarnessRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nsecret-order-42\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    source = {
        "malformed": "print('not json')\n",
        "nonzero": "raise SystemExit(7)\n",
        "timeout": "import time; time.sleep(2)\n",
    }[mode]
    bad.write_text(source, encoding="utf-8")

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--input",
            str(orders),
            "--evolve",
            "--max-rounds",
            "1",
            "--evaluator-command",
            f"{sys.executable} {bad}",
            "--timeout",
            "0.05" if mode == "timeout" else "2",
            "--json",
            "--home",
            str(tmp_path / "home"),
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["evolution"]["result"]["valid_candidates"] == 0
    assert runtime.evaluation_calls == 0


def test_detached_solve_propagates_objective_harness_without_secret(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = HarnessRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    captured: dict[str, object] = {}

    class Process:
        pid = 4242

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return Process()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    monkeypatch.setattr("famou.cli.os.getpgid", lambda pid: pid)
    harness = _write_harness(tmp_path)
    command = f"{sys.executable} {harness}"

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--evolve",
            "--detach",
            "--evaluator-command",
            command,
            "--json",
            "--home",
            str(tmp_path / "home"),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"
    child_command = captured["command"]
    assert isinstance(child_command, list)
    index = child_command.index("--evaluator-command")
    assert child_command[index + 1] == command
    assert "FAMOU_API_KEY" not in (captured["env"] or {})


def test_answer_can_resume_pending_contract_with_the_same_objective_harness(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = QuestionHarnessRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nsecret-order-42\n", encoding="utf-8")
    harness = _write_harness(tmp_path)
    command = f"{sys.executable} {harness}"
    home = tmp_path / "home"

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--input",
            str(orders),
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--evaluator-command",
            command,
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    awaiting = json.loads(capsys.readouterr().out)
    assert awaiting["status"] == "awaiting_input"

    assert main(
        [
            "answer",
            awaiting["run_id"],
            "cost",
            "--runtime",
            "mock",
            "--evaluator-command",
            command,
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    answered = json.loads(capsys.readouterr().out)
    assert answered["status"] == "succeeded"
    assert answered["evolution"]["result"]["best_candidate_id"] == "candidate-0002"
    assert answered["algorithm_outputs"][0]["path"] == "output/routes.csv"
    assert runtime.evaluation_calls == 0
