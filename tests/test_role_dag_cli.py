import json
import shlex
import sys
from pathlib import Path

from famou.cli import main


def test_cli_solve_role_dag_selects_five_stage_plan(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    assert main(["solve", "design a route", "--runtime", "mock", "--role-dag", "--json", "--home", str(home)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["compiler"]["plan_kind"] == "role_dag"
    status_code = main(["status", payload["run_id"], "--json", "--home", str(home)])
    assert status_code == 0
    status = json.loads(capsys.readouterr().out)
    plan_tasks = {task["plan_task_id"]: task for task in status["tasks"] if task["plan_task_id"]}
    assert set(plan_tasks) == {
        "data_discovery",
        "problem_formulator",
        "solver",
        "evaluator",
        "reviewer",
    }
    assert plan_tasks["reviewer"]["dependencies"] == [next(
        task["id"] for task in status["tasks"] if task["plan_task_id"] == "evaluator"
    )]


def test_cli_answer_reuses_role_dag_mode_from_manifest(tmp_path: Path, capsys) -> None:
    compiler = tmp_path / "compiler.py"
    compiler.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "text = sys.stdin.read()\n"
        "root = Path.cwd()\n"
        "if 'Role: Reviewer' in text:\n"
        " p = root / 'evaluate/review.md'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('# Review\\n'); print('role completed'); raise SystemExit\n"
        "if 'Role: Evaluator' in text:\n"
        " p = root / 'evaluate/evaluation.json'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({'schema_version':'1','evaluator_id':'fixture','validity':1,'quality':1,'combined_score':1,'detailed_scores':{},'error_info':[]})); print('role completed'); raise SystemExit\n"
        "if 'Role: ProblemFormulator' in text:\n"
        " p = root / 'solve/problem-formulation.md'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('# Formulation\\n'); print('role completed'); raise SystemExit\n"
        "if 'Role: DataDiscovery' in text:\n"
        " p = root / 'data/processed/data-profile.json'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({'schema_version':'1','inputs':[{'path':'data/raw/input.json','format':'json','row_count':0,'columns':[],'issues':['not staged']}]})); print('role completed'); raise SystemExit\n"
        "if 'A user answered' not in text:\n"
        " print(json.dumps({'status':'needs_input','questions':['Which objective?']}))\n"
        "else:\n"
        " print(json.dumps({'status':'compiled','contract':{'schema_version':'1','problem_id':'role-answer','problem_type':'routing','statement':'route','inputs':[{'path':'orders.csv','format':'csv','fields':{'id':'id'}}],'decision_variables':['route'],'objective':{'name':'distance','direction':'minimize'},'hard_constraints':[],'soft_constraints':[],'success_criteria':['serve all'],'deliverables':['route']}}))\n",
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(compiler))}"
    home = tmp_path / "home"
    assert main(["solve", "route orders", "--runtime", "subprocess", "--command", command, "--role-dag", "--json", "--home", str(home)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "awaiting_input"
    assert main(["answer", first["run_id"], "minimize distance", "--runtime", "subprocess", "--command", command, "--json", "--home", str(home)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "succeeded"
    status_code = main(["status", first["run_id"], "--json", "--home", str(home)])
    assert status_code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["conversation"]["plan_kind"] == "role_dag"
