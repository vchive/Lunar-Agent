"""User-facing solve intake through bundle generation, exact scoring and parent delivery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import draft_for_score
from test_bundle_population_cli import command

from lunar_evolution import cli
from lunar_evolution.config import Config
from lunar_evolution.runtime import MockRuntime, RuntimeResult
from lunar_evolution.solve_bundle import bundle_pipeline_sha256
from lunar_evolution.store import Store


class ConversationalBundleRuntime(MockRuntime):
    name = "conversational-bundle-fixture"

    def __init__(self, contract, *, clarify=False, after_compile=None, no_inputs=False):
        self.contract = contract
        self.clarify = clarify
        self.after_compile = after_compile
        self.no_inputs = no_inputs
        self.compiler_calls = 0
        self.generator_calls = 0
        self.generated_inputs = []

    def run(self, prompt, workspace, timeout=None):
        del timeout
        if "contract compiler" in prompt:
            self.compiler_calls += 1
            if self.clarify and self.compiler_calls == 1:
                return RuntimeResult(json.dumps({
                    "status": "needs_input", "questions": [{"question": "Which objective?", "options": ["maximize value"]}],
                }))
            if self.after_compile is not None:
                self.after_compile()
            return RuntimeResult(json.dumps({"status": "compiled", "contract": self.contract.to_dict()}))
        assert (workspace / "context/contract.json").is_file(), "ordinary plan or model evaluator was invoked"
        if self.no_inputs:
            assert not (workspace / "context/inputs").exists()
        else:
            self.generated_inputs.append((workspace / "context/inputs/value").read_bytes())
        if self.generator_calls >= 2:
            assert (workspace / "context/parent/source/solve/helper.py").is_file()
        score = (1, 2, 999, 9)[self.generator_calls]
        self.generator_calls += 1
        draft = draft_for_score(score)
        sources = dict(draft.source_files)
        if self.no_inputs:
            sources["solve/main.py"] = sources["solve/main.py"].replace(
                'limit = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "value").read_text())',
                "limit = 10",
            )
        return RuntimeResult(json.dumps({
            "files": sources, "entrypoint": draft.filename,
            "metadata": {"producer_score_claim": 999999},
        }))


def setup(tmp_path, monkeypatch, *, clarify=False, after_compile=None, no_inputs=False):
    context, _ = command(tmp_path)
    runtime = ConversationalBundleRuntime(
        context.contract, clarify=clarify, after_compile=after_compile, no_inputs=no_inputs,
    )
    monkeypatch.setattr(cli, "build_runtime", lambda *_: runtime)
    args = [
        "solve", "Choose a feasible value and deliver the complete working project.",
        "--runtime", "mock", "--workspace", str(tmp_path / "conversation"),
        "--evolve", "--bundle-profile", str(tmp_path / "profile.json"),
        "--input", str(tmp_path / "inputs/value"),
        "--max-rounds", "1", "--stagnation-rounds", "3", "--population-size", "2",
        "--offspring-per-iteration", "2", "--islands", "2", "--seed", "7", "--timeout", "3",
        "--home", str(tmp_path / "home"), "--json",
    ]
    if no_inputs:
        runtime.contract = replace(runtime.contract, inputs=(replace(
            runtime.contract.inputs[0], format="inline", fields={"value": "Constant limit 10, embedded in the program."},
        ),))
        index = args.index("--input")
        del args[index:index + 2]
        harness_path = tmp_path / "harness.py"
        harness = harness_path.read_text().replace('limit = int(Path("inputs/value").read_text())', "limit = 10").encode()
        harness_path.write_bytes(harness)
        profile_path = tmp_path / "profile.json"
        profile = json.loads(profile_path.read_text())
        profile["inputs"] = []
        profile["evaluator"]["harness_sha256"] = hashlib.sha256(harness).hexdigest()
        profile["evaluator"]["harness_size"] = len(harness)
        profile_path.write_text(json.dumps(profile))
    return context, runtime, args


def counts(workspace):
    return {path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in workspace.rglob("count")}


def test_solve_routes_compiled_contract_to_bundle_child_and_delivers_parent_outputs(tmp_path, monkeypatch, capsys):
    context, runtime, args = setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    parent = Path(payload["workspace"])
    evolution = payload["evolution"]
    assert payload["status"] == "succeeded"
    assert evolution["status"] == "succeeded"
    assert evolution["result"]["best_score"] == 9
    assert evolution["result"]["valid_candidates"] == 3
    assert evolution["materialization"]["mode"] == "bundle"
    assert evolution["materialization"]["status"] == "succeeded"
    assert json.loads((parent / "output/result.json").read_text())["value"] == 9
    delivery = parent / evolution["materialization"]["delivery_path"]
    assert (delivery / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert runtime.compiler_calls == 1 and runtime.generator_calls == 4
    assert runtime.generated_inputs == [b"10"] * 4
    assert set(counts(parent).values()) == {b"x"}
    assert len(counts(parent)) == 4
    store = Store(tmp_path / "home/state.db")
    events = store.list_events(payload["run_id"])
    request = next(item["payload"] for item in events if item["type"] == "evolution_requested")
    assert request["bundle_profile_sha256"] == bundle_pipeline_sha256(context.bundle_pipeline)
    assert str(tmp_path) not in json.dumps(request)
    assert "harness_path" not in request and "bundle_profile" not in request
    assert len([item for item in events if item["type"] == "evolution_linked"]) == 1
    assert len([item for item in events if item["type"] == "bundle_candidate_delivered"]) == 1
    assert all(item["type"] != "evolved_candidate_materialized" for item in events)
    status = cli._status_payload(Config(tmp_path / "home"), payload["run_id"])
    assert status["evolution"]["linked"]["materialization"]["mode"] == "bundle"


@pytest.mark.parametrize("resume_command", ["solve", "resume"])
def test_terminal_conversational_bundle_resume_reuses_child_and_delivery_without_evolve_flag(tmp_path, monkeypatch, capsys, resume_command):
    _, runtime, args = setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    before = counts(Path(first["workspace"]))
    resume = ["solve", "--resume", "--run-id", first["run_id"]] if resume_command == "solve" else ["resume", first["run_id"]]
    resume.extend(("--bundle-profile", str(tmp_path / "profile.json"), "--runtime", "mock",
                   "--home", str(tmp_path / "home"), "--json"))
    assert cli.main(resume) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["evolution"]["run_id"] == first["evolution"]["run_id"]
    assert second["evolution"]["materialization"] == first["evolution"]["materialization"]
    assert counts(Path(first["workspace"])) == before
    assert (runtime.compiler_calls, runtime.generator_calls) == (1, 4)


@pytest.mark.parametrize("mode", ["solve", "resume", "answer"])
@pytest.mark.parametrize("profile", ["missing", "changed"])
def test_continue_requires_matching_profile_before_answer_or_model_work(tmp_path, monkeypatch, capsys, mode, profile):
    _, runtime, args = setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    assert initial["status"] == "awaiting_input"
    parent = Path(initial["workspace"])
    store = Store(tmp_path / "home/state.db")
    pending = store.pending_input(initial["run_id"])
    if mode == "solve":
        followup = ["solve", "--resume", "--run-id", initial["run_id"]]
    elif mode == "resume":
        followup = ["resume", initial["run_id"]]
    else:
        followup = ["answer", initial["run_id"], "maximize value"]
    if profile == "changed":
        path = tmp_path / "profile.json"
        payload = json.loads(path.read_text())
        payload["dependency_sha256"] = "e" * 64
        path.write_text(json.dumps(payload))
        followup.extend(("--bundle-profile", str(path)))
    followup.extend(("--runtime", "mock", "--home", str(tmp_path / "home"), "--json"))
    assert cli.main(followup) == 2
    assert "solve_bundle_profile_" in json.loads(capsys.readouterr().err)["error"]
    assert store.pending_input(initial["run_id"]) == pending
    assert not list(parent.rglob("input-answer.json"))
    assert (runtime.compiler_calls, runtime.generator_calls) == (1, 0)
    assert not (parent / "evolution-run").exists()


def test_answer_uses_matching_profile_to_finish_bundle_handoff(tmp_path, monkeypatch, capsys):
    _, runtime, args = setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    pending = json.loads(capsys.readouterr().out)
    assert cli.main([
        "answer", pending["run_id"], "maximize value", "--bundle-profile", str(tmp_path / "profile.json"),
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["evolution"]["materialization"]["mode"] == "bundle"
    assert (runtime.compiler_calls, runtime.generator_calls) == (2, 4)


def test_generation_uses_parent_staged_input_after_original_input_changes(tmp_path, monkeypatch, capsys):
    _, runtime, args = setup(
        tmp_path, monkeypatch,
        after_compile=lambda: (tmp_path / "inputs/value").write_bytes(b"99"),
    )
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evolution"]["result"]["best_score"] == 9
    assert runtime.generated_inputs == [b"10"] * 4
    assert (Path(payload["workspace"]) / "data/raw/value").read_bytes() == b"10"


def test_bundle_contract_without_declared_outputs_rejects_before_child_creation(tmp_path, monkeypatch, capsys):
    _, runtime, args = setup(tmp_path, monkeypatch)
    runtime.contract = replace(runtime.contract, outputs=())
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "solve_bundle_outputs_required"
    assert not (tmp_path / "conversation/evolution-run").exists()
    assert (runtime.compiler_calls, runtime.generator_calls) == (1, 0)


@pytest.mark.parametrize("precompiler_interruption", [False, True])
def test_bundle_without_inputs_runs_and_recovers_before_workspace_creation(tmp_path, monkeypatch, capsys, precompiler_interruption):
    _, runtime, args = setup(tmp_path, monkeypatch, no_inputs=True)
    if precompiler_interruption:
        with monkeypatch.context() as interruption:
            def fail_before_compilation(*_args, **_kwargs):
                raise OSError("injected interruption before compilation")

            interruption.setattr(cli.LocalController, "resume_conversational", fail_before_compilation)
            assert cli.main(args) == 2
            assert "injected interruption" in json.loads(capsys.readouterr().err)["error"]
        parent = Store(tmp_path / "home/state.db").get_run_by_workspace(tmp_path / "conversation")
        assert parent is not None and not parent.workspace.exists()
        assert (runtime.compiler_calls, runtime.generator_calls) == (0, 0)
        args = ["resume", parent.id, "--bundle-profile", str(tmp_path / "profile.json"),
                "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "succeeded"
    assert result["evolution"]["result"]["best_score"] == 9
    assert result["evolution"]["materialization"]["status"] == "succeeded"
    assert runtime.generated_inputs == []
    assert (runtime.compiler_calls, runtime.generator_calls) == (1, 4)


@pytest.mark.parametrize("changed", ["child_symlink", "parent_link", "child_link"])
def test_bundle_resume_validates_child_path_and_both_links_before_input_mutation(tmp_path, monkeypatch, capsys, changed):
    _, runtime, args = setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    parent = Path(first["workspace"])
    child_id = first["evolution"]["run_id"]
    store = Store(tmp_path / "home/state.db")
    if changed == "child_symlink":
        child = parent / "evolution-run"
        moved = tmp_path / "moved-child"
        child.rename(moved)
        child.symlink_to(moved, target_is_directory=True)
    elif changed == "parent_link":
        store.append_event(first["run_id"], "evolution_linked", {
            "evolution_run_id": "different-child", "strategy": "population",
            "contract_sha256": "e" * 64,
        })
    else:
        store.append_event(child_id, "evolution_parent_linked", {
            "parent_run_id": "different-parent", "contract_sha256": "e" * 64,
        })
    extra = tmp_path / "extra-input"
    extra.write_bytes(b"new input must not be staged")
    assert cli.main([
        "solve", "--resume", "--run-id", first["run_id"],
        "--bundle-profile", str(tmp_path / "profile.json"), "--input", str(extra),
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert not (parent / "data/raw/extra-input").exists()
    assert (runtime.compiler_calls, runtime.generator_calls) == (1, 4)


@pytest.mark.parametrize("inputs", ["missing", "different", "extra", "renamed"])
def test_profile_must_match_exact_parent_input_ledger_before_compilation(tmp_path, monkeypatch, capsys, inputs):
    _, runtime, args = setup(tmp_path, monkeypatch)
    index = args.index("--input")
    if inputs == "missing":
        del args[index:index + 2]
    elif inputs == "different":
        alternative = tmp_path / "alternative"
        alternative.write_bytes(b"99")
        args[index + 1] = str(alternative) + "=value"
    elif inputs == "renamed":
        args[index + 1] += "=other-value"
    else:
        extra = tmp_path / "extra"
        extra.write_bytes(b"extra")
        args.extend(("--input", str(extra)))
    assert cli.main(args) == 2
    assert "solve_bundle" in json.loads(capsys.readouterr().err)["error"]
    assert (runtime.compiler_calls, runtime.generator_calls) == (0, 0)
    assert not (tmp_path / "conversation/evolution-run").exists()


@pytest.mark.parametrize("invalid", ["no_evolve", "detach", "compiled", "evaluator", "openevolve", "profile"])
def test_solve_rejects_conflicting_bundle_setup_before_home_or_model(tmp_path, monkeypatch, capsys, invalid):
    _, runtime, args = setup(tmp_path, monkeypatch)
    if invalid == "no_evolve":
        args.remove("--evolve")
    elif invalid == "detach":
        args.append("--detach")
    elif invalid == "compiled":
        args.append("--compile-evaluator")
    elif invalid == "evaluator":
        args.extend(("--evaluator-command", "unused"))
    elif invalid == "openevolve":
        args.extend(("--strategy", "openevolve"))
    else:
        (tmp_path / "profile.json").write_text("invalid")
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home").exists()
    assert not (tmp_path / "conversation").exists()
    assert (runtime.compiler_calls, runtime.generator_calls) == (0, 0)
