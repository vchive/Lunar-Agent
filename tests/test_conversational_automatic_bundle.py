"""Automatic multi-file solve intake preserves its mode across answer and resume."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score
from test_conversational_bundle import counts

from famou import cli
from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.evolution import EvolutionError
from famou.runtime import MockRuntime, RuntimeResult
from famou.store import Store

SNAPSHOT_SOURCE = '''"""compiled-evaluator-hidden-marker"""
import json
import sys
from pathlib import Path

def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    limit = int(Path("inputs/value").read_text())
    value = json.loads(Path("output/result.json").read_text())["value"]
    valid = int(type(value) is int and 0 <= value <= limit)
    print(json.dumps({"schema_version": "1", "evaluator_id": "compiled-bundle",
        "validity": valid, "quality": float(value) if valid else None,
        "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value exceeds the input limit."}]}))

if __name__ == "__main__":
    main()
'''


def _suite(*, audit=False):
    prefix = "audit" if audit else "compiler"
    values = (2, 8, 11) if audit else (1, 9, 999)
    return {
        "schema_version": "1", "constraint_coverage": ["out_of_bounds"],
        "probes": [{
            "name": f"{prefix}-{name}", "constraint_id": None if index < 2 else "out_of_bounds",
            "expected_validity": 1 if index < 2 else 0,
            "files": [{"path": "data/raw/value", "content": "10"},
                      {"path": "output/result.json", "content": json.dumps({"value": value})}],
        } for index, (name, value) in enumerate(zip(("low", "high", "invalid"), values, strict=True))],
        "score_order": [{"better": f"{prefix}-high", "worse": f"{prefix}-low"}],
    }


class AutomaticBundleRuntime(MockRuntime):
    name = "automatic-bundle-fixture"

    def __init__(self, contract, *, clarify=False):
        self.contract, self.clarify = contract, clarify
        self.contract_calls = self.bundle_calls = self.audit_calls = self.generator_calls = 0
        self.isolated_calls = 0
        self.generator_workspaces = []

    def run_isolated(self, prompt, workspace, timeout=None):
        self.isolated_calls += 1
        return self.run(prompt, workspace, timeout)

    def run(self, prompt, workspace, timeout=None):
        del timeout
        if "contract compiler" in prompt:
            self.contract_calls += 1
            if self.clarify and self.contract_calls == 1:
                return RuntimeResult(json.dumps({
                    "status": "needs_input", "questions": [{"question": "Which objective?", "options": ["maximize value"]}],
                }))
            return RuntimeResult(json.dumps({"status": "compiled", "contract": self.contract.to_dict()}))
        if "frozen local evaluator bundle" in prompt:
            self.bundle_calls += 1
            assert "request.json" in prompt
            return RuntimeResult(json.dumps({
                **_suite(), "objective": "Maximize the integer value while remaining within its input bound.",
                "evaluator_source": SNAPSHOT_SOURCE,
            }))
        if "adversarial evaluator auditor" in prompt:
            self.audit_calls += 1
            assert "compiler-high" not in prompt
            return RuntimeResult(json.dumps(_suite(audit=True)))
        assert (workspace / "context/contract.json").is_file(), "ordinary DAG or model evaluator was invoked"
        assert (workspace / "context/inputs/value").read_bytes() == b"10"
        assert all(marker not in prompt for marker in ("compiled-evaluator-hidden-marker", "compiler-high", "audit-high", "scoring_contract"))
        assert not list(workspace.rglob("evaluator.py")) and not (workspace / "scoring").exists()
        self.generator_workspaces.append(workspace)
        draft = draft_for_score((1, 2, 999, 9)[self.generator_calls])
        self.generator_calls += 1
        return RuntimeResult(json.dumps({"files": draft.source_files, "entrypoint": draft.filename}))


def automatic_setup(tmp_path, monkeypatch, *, clarify=False):
    context = build_context(tmp_path)
    context.bundle_pipeline.harness_path.unlink()
    payload = context.contract.to_dict()
    payload["hard_constraints"] = [{
        "id": "out_of_bounds", "description": "The selected integer is between zero and the input limit.",
        "source": "user_confirmed", "verification": "independent",
    }]
    runtime = AutomaticBundleRuntime(AlgorithmProblemContract.from_dict(payload), clarify=clarify)
    monkeypatch.setattr(cli, "build_runtime", lambda *_: runtime)
    args = [
        "solve", "Choose a feasible integer and deliver its complete working project.",
        "--runtime", "mock", "--workspace", str(tmp_path / "conversation"),
        "--evolve", "--multi-file", "--input", str(tmp_path / "inputs/value"),
        "--max-rounds", "1", "--stagnation-rounds", "3", "--population-size", "2",
        "--offspring-per-iteration", "2", "--islands", "2", "--seed", "7", "--timeout", "3",
        "--home", str(tmp_path / "home"), "--json",
    ]
    return runtime, args


@pytest.mark.parametrize("arguments", [
    ["--multi-file"],
    ["--evolve", "--multi-file", "--detach"],
    ["--evolve", "--multi-file", "--bundle-profile", "missing.json"],
    ["--evolve", "--multi-file", "--evaluator-command", "/not-used"],
    ["--evolve", "--multi-file", "--openevolve-command", "/not-used"],
    ["--evolve", "--multi-file", "--strategy", "openevolve"],
])
def test_automatic_bundle_invalid_modes_fail_before_creating_run(tmp_path, monkeypatch, capsys, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid options must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main(["solve", "optimize", *arguments, "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "--multi-file" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("extra", [[], ["--compile-evaluator"]])
def test_automatic_bundle_request_has_only_additive_mode_marker(extra):
    parser = cli.build_parser()
    ordinary = parser.parse_args(["solve", "optimize", "--evolve"])
    automatic = parser.parse_args(["solve", "optimize", "--evolve", "--multi-file", *extra])
    cli._prepare_conversational_bundle(automatic)
    old = cli._evolution_request_payload(ordinary)
    new = cli._evolution_request_payload(automatic)
    assert "bundle_mode" not in old and "bundle_profile_sha256" not in old
    assert new == {**old, "compile_evaluator": True, "bundle_mode": "compiled"}
    assert "bundle_profile" not in new and "harness_path" not in new


@pytest.mark.parametrize("command", [
    ["solve", "--resume", "--run-id", "parent"], ["resume", "parent"], ["answer", "parent", "continue"],
])
def test_automatic_mode_is_restored_without_repeating_flags(command):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
    ]))
    args = parser.parse_args(command)
    cli._prepare_conversational_bundle(args)
    cli._validate_conversational_bundle_request(args, request)
    resumed = cli._evolution_args(args, request)
    assert resumed.multi_file is True and resumed.compile_evaluator is True and resumed.evolve is True
    assert getattr(resumed, "bundle_profile", None) is None


@pytest.mark.parametrize("mode", [None, "single", False, {}, "external"])
def test_invalid_automatic_mode_marker_is_rejected(mode):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve"]))
    request.update(bundle_mode=mode, compile_evaluator=True)
    with pytest.raises(EvolutionError, match="mode_invalid"):
        cli._validate_conversational_bundle_request(
            parser.parse_args(["solve", "--resume", "--run-id", "parent"]), request,
        )


@pytest.mark.parametrize("arguments", [["--evaluator-command", "/not-used"], ["--strategy", "openevolve"], ["--bundle-profile", "missing"]])
def test_automatic_resume_rejects_switch_to_another_mode(arguments):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve", "--multi-file"]))
    args = parser.parse_args(["solve", "--resume", "--run-id", "parent", *arguments])
    with pytest.raises(ValueError, match="--multi-file"):
        cli._validate_conversational_bundle_request(args, request)


def test_existing_single_file_handoff_cannot_switch_to_automatic_bundle():
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve", "--compile-evaluator"]))
    args = parser.parse_args(["solve", "--resume", "--run-id", "parent", "--multi-file"])
    with pytest.raises(EvolutionError, match="mode_mismatch"):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("resume_command", ["solve", "resume"])
def test_automatic_solve_delivers_scored_bundle_and_resumes_without_compilation(tmp_path, monkeypatch, capsys, resume_command):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    if resume_command == "resume":
        args.append("--compile-evaluator")
    assert not (tmp_path / "profile.json").exists()
    assert not (tmp_path / "harness.py").exists()
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    parent = Path(first["workspace"])
    assert first["status"] == "succeeded"
    assert first["evolution"]["result"]["best_score"] == 9
    assert first["evolution"]["result"]["valid_candidates"] == 3
    delivery = first["evolution"]["materialization"]
    assert delivery["mode"] == "bundle" and delivery["status"] == "succeeded"
    assert json.loads((parent / "output/result.json").read_text())["value"] == 9
    copied = parent / delivery["delivery_path"]
    assert (copied / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert (copied / "evaluation/evaluator.py").read_bytes() == (parent / "evaluator-bundle/evaluator.py").read_bytes()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert runtime.isolated_calls == 3
    store = Store(tmp_path / "home/state.db")
    events = store.list_events(first["run_id"])
    rows = store.list_artifacts(first["run_id"])
    request = next(event["payload"] for event in events if event["type"] == "evolution_requested")
    assert request["bundle_mode"] == "compiled" and request["compile_evaluator"] is True
    assert "bundle_profile_sha256" not in request and "harness_path" not in request
    assert str(tmp_path) not in json.dumps(request)
    assert len([event for event in events if event["type"] == "bundle_profile_prepared"]) == 1
    assert (parent / "bundle-profile.json").is_file()
    assert not any(event["type"] == "evolved_candidate_materialized" for event in events)
    before = counts(parent)
    assert len(before) == 4 and set(before.values()) == {b"x"}
    (tmp_path / "inputs/value").write_bytes(b"99")
    followup = ["solve", "--resume", "--run-id", first["run_id"]] if resume_command == "solve" else ["resume", first["run_id"]]
    assert cli.main([*followup, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["evolution"]["materialization"] == delivery
    assert second["evolution"]["run_id"] == first["evolution"]["run_id"]
    assert counts(parent) == before
    assert store.list_artifacts(first["run_id"]) == rows
    assert store.list_events(first["run_id"]) == events
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert cli._status_payload(Config(tmp_path / "home"), first["run_id"])["evolution"]["linked"]["materialization"] == delivery


@pytest.mark.parametrize("repeat_mode", [False, True])
def test_automatic_answer_prepares_profile_after_clarification(tmp_path, monkeypatch, capsys, repeat_mode):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    parent = Path(initial["workspace"])
    assert initial["status"] == "awaiting_input"
    assert not (parent / "bundle-profile.json").exists()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)
    extra = ["--multi-file"] if repeat_mode else []
    assert cli.main([
        "answer", initial["run_id"], "maximize value", *extra,
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "succeeded" and second["evolution"]["materialization"]["mode"] == "bundle"
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (2, 1, 1, 4)


@pytest.mark.parametrize("changed", ["profile", "missing_profile", "harness", "input", "link"])
def test_automatic_resume_rejects_changed_preparation_before_compiler_or_candidate(tmp_path, monkeypatch, capsys, changed):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    parent = Path(first["workspace"])
    if changed == "missing_profile":
        (parent / "bundle-profile.json").unlink()
    elif changed == "link":
        store = Store(tmp_path / "home/state.db")
        with store._connect() as connection:
            connection.execute("UPDATE runs SET workspace = ? WHERE id = ?", (str(tmp_path / "wrong-child"), first["evolution"]["run_id"]))
    else:
        target = parent / {"profile": "bundle-profile.json", "harness": "evaluator-bundle/evaluator.py", "input": "data/raw/value"}[changed]
        target.chmod(0o600)
        target.write_bytes(target.read_bytes() + b" ")
    before = counts(parent)
    assert cli.main([
        "resume", first["run_id"], "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert counts(parent) == before
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)


def test_automatic_pending_mode_conflict_preserves_answer_and_compiler_count(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    before = store.pending_input(initial["run_id"])
    assert cli.main([
        "answer", initial["run_id"], "maximize value", "--evaluator-command", "/not-used",
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "--multi-file" in json.loads(capsys.readouterr().err)["error"]
    assert store.pending_input(initial["run_id"]) == before
    assert not list(Path(initial["workspace"]).rglob("input-answer.json"))
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)


def test_pending_input_drift_is_rejected_before_answer_and_contract_compiler(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    parent = Path(initial["workspace"])
    store = Store(tmp_path / "home/state.db")
    pending = store.pending_input(initial["run_id"])
    (parent / "data/raw/value").write_bytes(b"11")
    assert cli.main([
        "answer", initial["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert store.pending_input(initial["run_id"]) == pending
    assert not list(parent.rglob("input-answer.json"))
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)


def test_resume_after_frozen_evaluator_before_profile_does_not_recompile(tmp_path, monkeypatch, capsys):
    from famou import automatic_solve_bundle

    class SimulatedCrash(BaseException):
        pass

    def stop_before_profile(*args, **kwargs):
        raise SimulatedCrash("stopped after frozen evaluator publication")

    runtime, args = automatic_setup(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(automatic_solve_bundle, "_write_profile", stop_before_profile)
        with pytest.raises(SimulatedCrash):
            cli.main(args)
    capsys.readouterr()
    store = Store(tmp_path / "home/state.db")
    parent = store.get_run_by_workspace(tmp_path / "conversation")
    assert parent is not None and parent.current_plan_id is not None
    assert (Path(parent.workspace) / "evaluator-bundle/manifest.json").is_file()
    assert not (Path(parent.workspace) / "bundle-profile.json").exists()
    assert not (Path(parent.workspace) / "evolution-run").exists()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 0)
    assert cli.main([
        "resume", parent.id, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    final = json.loads(capsys.readouterr().out)
    assert final["evolution"]["materialization"]["mode"] == "bundle"
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
