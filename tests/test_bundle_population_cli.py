"""A real command generator, execution, scoring and delivery through the bundle CLI."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest
from test_bundle_population import MAIN_SOURCE, build_context

from lunar_evolution import cli
from lunar_evolution.evolution import CandidateArchive


def command(tmp_path):
    context = build_context(tmp_path)
    pipeline = context.bundle_pipeline
    profile = {
        "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
        "evaluator": pipeline.evaluator.to_dict(),
        "harness_path": "harness.py", "input_root": "inputs",
        "inputs": [item.to_dict() for item in pipeline.inputs],
        "command": list(pipeline.command), "environment": {},
        "timeout_seconds": pipeline.timeout_seconds, "max_output_bytes": pipeline.max_output_bytes,
        "dependency_sha256": pipeline.dependency_sha256,
        "environment_sha256": pipeline.environment_sha256,
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    (tmp_path / "contract.json").write_text(json.dumps(context.contract.to_dict()))
    generator = tmp_path / "generator.py"
    generator.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "request = json.loads(Path(sys.argv[1]).read_text())\n"
        "with Path(__file__).with_name('generator-calls').open('a') as stream:\n"
        "    stream.write('x')\n"
        "score = [1, 2, 999, 9][len(request['archive'])]\n"
        "helper = f'def choose(limit):\\n    return {score}\\n'\n"
        f"print(json.dumps({{'files': {{'solve/main.py': {MAIN_SOURCE!r}, 'solve/helper.py': helper}}, "
        "'entrypoint': 'solve/main.py', 'metadata': {'producer_score_claim': 999999}}))\n"
    )
    destination = tmp_path / "deliveries"
    destination.mkdir()
    args = [
        "evolve-bundle", str(tmp_path / "contract.json"),
        "--profile", str(tmp_path / "profile.json"),
        "--generator-command", shlex.join((str(Path(sys.executable).resolve()), str(generator))),
        "--workspace", str(context.workspace), "--home", str(tmp_path / "home"),
        "--max-rounds", "1", "--stagnation-rounds", "3", "--population-size", "2",
        "--offspring-per-iteration", "2", "--islands", "2",
        "--migration-interval", "1", "--migration-rate", "1", "--seed", "7",
        "--timeout", "3", "--destination-root", str(destination), "--json",
    ]
    return context, args


def _snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_cli_runs_scores_delivers_and_resumes_without_reexecution(tmp_path, capsys):
    context, args = command(tmp_path)
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert payload["status"] == "completed"
    assert payload["run_status"] == "succeeded"
    assert payload["evaluated_candidates"] == 4
    assert payload["valid_candidates"] == 3
    assert payload["best_score"] == 9
    assert payload["delivery"]["status"] == "delivered"
    delivered = Path(payload["delivery"]["delivery_path"])
    assert (delivered / "source/solve/main.py").read_text() == MAIN_SOURCE
    assert (delivered / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert json.loads((delivered / "output/result.json").read_text())["value"] == 9
    assert (tmp_path / "generator-calls").read_text() == "xxxx"
    before = _snapshot(context.workspace)

    assert cli.main([*args, "--resume", "--run-id", payload["run_id"]]) == 0
    resumed = json.loads(capsys.readouterr().out)

    assert resumed["run_id"] == payload["run_id"]
    assert resumed["best_candidate_id"] == payload["best_candidate_id"]
    assert resumed["delivery"]["delivery_sha256"] == payload["delivery"]["delivery_sha256"]
    assert resumed["delivery"]["delivery_path"] != payload["delivery"]["delivery_path"]
    assert _snapshot(context.workspace) == before
    assert (tmp_path / "generator-calls").read_text() == "xxxx"


def test_cli_inspects_delivery_without_home_and_rejects_changed_output(tmp_path, monkeypatch, capsys):
    context, args = command(tmp_path)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    delivery = payload["delivery"]
    before = _snapshot(context.workspace)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("inspection initialized home/Store"))
    inspect = [
        "candidate-bundle", "inspect-delivery", delivery["delivery_path"],
        "--delivery-sha256", delivery["delivery_sha256"],
        "--json", "--home", str(tmp_path / "no-home"),
    ]

    assert cli.main(inspect) == 0
    assert json.loads(capsys.readouterr().out) == delivery
    (Path(delivery["delivery_path"]) / "output/result.json").write_text('{"value": 0}')
    assert cli.main(inspect) == 2
    error = capsys.readouterr()
    assert "bundle_delivery_invalid" in error.out + error.err
    assert not (tmp_path / "no-home").exists()
    assert _snapshot(context.workspace) == before
    assert (tmp_path / "generator-calls").read_text() == "xxxx"


@pytest.mark.parametrize("changed", ["helper", "evaluation", "contract", "configuration"])
def test_cli_resume_rejects_changed_evidence_before_generation_or_delivery(tmp_path, capsys, changed):
    context, args = command(tmp_path)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    candidate = CandidateArchive(context.workspace).best()
    if changed == "helper":
        (context.workspace / candidate.code_path).with_name("helper.py").write_text("changed\n")
    elif changed == "evaluation":
        root = context.workspace / candidate.bundle_evidence["evaluation_path"]
        (root / "output/result.json").write_text('{"value": 0}')
    elif changed == "contract":
        path = tmp_path / "contract.json"
        value = json.loads(path.read_text())
        value["statement"] += " Changed."
        path.write_text(json.dumps(value))
    else:
        args[args.index("--seed") + 1] = "8"
    deliveries = sorted((tmp_path / "deliveries").iterdir())

    assert cli.main([*args, "--resume", "--run-id", payload["run_id"]]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert (tmp_path / "generator-calls").read_text() == "xxxx"
    assert sorted((tmp_path / "deliveries").iterdir()) == deliveries


@pytest.mark.parametrize("invalid", [
    "profile", "profile_harness", "profile_input", "contract", "strategy", "budget",
    "resume_without_id", "id_without_resume", "generator", "destination",
])
def test_cli_rejects_invalid_setup_before_home_or_run_creation(tmp_path, capsys, invalid):
    context, args = command(tmp_path)
    if invalid == "profile":
        path = tmp_path / "profile.json"
        value = json.loads(path.read_text())
        value["unknown"] = True
        path.write_text(json.dumps(value))
    elif invalid == "profile_harness":
        (tmp_path / "harness.py").write_text("changed\n")
    elif invalid == "profile_input":
        (tmp_path / "inputs/value").write_text("99")
    elif invalid == "contract":
        (tmp_path / "contract.json").write_text('{"schema_version":"1","schema_version":"2"}')
    elif invalid == "strategy":
        path = tmp_path / "contract.json"
        value = json.loads(path.read_text())
        value["evolution"]["strategy"] = "openevolve"
        path.write_text(json.dumps(value))
    elif invalid == "budget":
        args[args.index("--max-rounds") + 1] = "0"
    elif invalid == "resume_without_id":
        args.append("--resume")
    elif invalid == "id_without_resume":
        args.extend(("--run-id", "not-a-new-run"))
    elif invalid == "generator":
        args[args.index("--generator-command") + 1] = "relative-command"
    else:
        args[args.index("--destination-root") + 1] = str(tmp_path / "missing-destination")

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert json.loads(output.err)["error"]
    assert not (tmp_path / "home").exists()
    assert not (context.workspace / "evolution").exists()
    assert not (tmp_path / "generator-calls").exists()
