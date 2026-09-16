"""Runtime workers generating real multi-file candidates through controller delivery."""

from __future__ import annotations

import json

import pytest
from test_bundle_population import HARNESS_SOURCE, MAIN_SOURCE, build_context, draft_for_score

from famou.agent_evolution import MAX_GENERATION_PROMPT_BYTES, AgentCandidateGenerator
from famou.agents import RuntimeAgentAdapter
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import CandidateArchive, EvolutionError, GenerationRequest
from famou.runtime import MockRuntime, RuntimeResult


class BundleFixtureRuntime:
    name = "bundle-generation-runtime-fixture"

    def __init__(self, scores=(1, 2, 999, 9)):
        self.scores = iter(scores)
        self.calls = []

    def run(self, prompt, workspace, timeout=None):
        context = json.loads((workspace / "context/context.json").read_bytes())
        assert len(prompt.encode("utf-8")) <= MAX_GENERATION_PROMPT_BYTES
        assert context["protocol"] == "lunar-agent-bundle-generation-v1"
        assert context["execution"]["input_root_env"] == "LUNAR_CANDIDATE_INPUT_ROOT"
        assert context["execution"]["cwd"] == "."
        assert (workspace / context["inputs"][0]["context_path"]).read_bytes() == b"10"
        assert HARNESS_SOURCE not in prompt
        assert not any(
            path.read_bytes() == HARNESS_SOURCE.encode()
            for path in workspace.rglob("*") if path.is_file()
        )
        parent = context["parent"]
        if parent is not None:
            source = parent["source"]
            assert source["file_count"] == 2
            assert (workspace / source["files_path"]).is_file()
            root = workspace / source["root"]
            assert {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} == {
                "solve/main.py", "solve/helper.py",
            }
            assert (root / "solve/main.py").read_text() == MAIN_SOURCE
            assert "def choose(limit):" in (root / "solve/helper.py").read_text()
        self.calls.append((workspace, context, prompt, timeout))
        draft = draft_for_score(next(self.scores))
        return RuntimeResult(json.dumps({
            "entrypoint": draft.filename, "files": draft.source_files,
            "metadata": {"producer_score_claim": 999999},
        }))

    def cancel(self):
        pass

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        del observer


def _generator(context, runtime):
    return AgentCandidateGenerator(
        RuntimeAgentAdapter(runtime, roles=("solver",)), contract=context.contract,
        bundle_pipeline=context.bundle_pipeline, timeout=2,
    )


def _execution_counts(workspace):
    return {path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in workspace.rglob("count")}


def test_runtime_agent_bundle_population_delivers_and_terminal_resume_invokes_no_worker(tmp_path):
    context = build_context(tmp_path)
    runtime = BundleFixtureRuntime()
    generator = _generator(context, runtime)
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    run = controller.create_evolution_run(context.contract, workspace=context.workspace)
    settled, result = controller.run_evolution(
        run.id, context.contract, generator, context.bundle_pipeline, context.config,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert settled.status.value == "succeeded" and result.best_score == 9
    assert len(runtime.calls) == 4
    assert len({call[0] for call in runtime.calls}) == 4
    assert sum(call[1]["parent"] is not None for call in runtime.calls) == 2
    records = CandidateArchive(context.workspace).records()
    assert [item.evaluation.combined_score for item in records] == [1, 2, 0, 9]
    assert records[2].evaluation.validity == 0
    assert len({item.source_sha256 for item in records}) == 1
    assert len({item.bundle_evidence["bundle_sha256"] for item in records}) == 4
    counts = _execution_counts(context.workspace)
    assert len(counts) == 4 and set(counts.values()) == {b"x"}
    destination = tmp_path / "deliveries"
    destination.mkdir()
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    assert json.loads((delivery.delivery_path / "output/result.json").read_bytes())["value"] == 9
    assert (delivery.delivery_path / "source/solve/main.py").read_text() == MAIN_SOURCE
    assert (delivery.delivery_path / "source/solve/helper.py").read_text().endswith("return 9\n")

    # A recreated runtime would raise StopIteration if any worker call occurred on terminal
    # resume, and the retained execution counters also rule out candidate re-execution.
    unused = BundleFixtureRuntime(scores=())
    _, resumed = controller.run_evolution(
        run.id, context.contract, _generator(context, unused), context.bundle_pipeline,
        context.config, resume=True, bundle_pipeline=context.bundle_pipeline,
    )
    assert resumed == result and unused.calls == []
    assert _execution_counts(context.workspace) == counts


def test_recreated_bundle_generator_never_reuses_previous_context_workspace(tmp_path):
    context = build_context(tmp_path)
    request = GenerationRequest(0, None, (), (), context.workspace)
    first = BundleFixtureRuntime(scores=(1,))
    draft = _generator(context, first)(request)
    previous = first.calls[0][0]
    (previous / "stale-generation-marker.txt").write_text("from an earlier invocation")
    second = BundleFixtureRuntime(scores=(2,))
    replacement = _generator(context, second)(request)
    current = second.calls[0][0]
    assert current != previous
    assert not (current / "stale-generation-marker.txt").exists()
    assert draft.source_files["solve/helper.py"] != replacement.source_files["solve/helper.py"]
    assert not _execution_counts(context.workspace)


def test_bundle_input_drift_refuses_runtime_generation_before_candidate_execution(tmp_path):
    context = build_context(tmp_path)
    runtime = BundleFixtureRuntime(scores=(9,))
    generator = _generator(context, runtime)
    (context.bundle_pipeline.input_root / "value").write_bytes(b"11")
    request = GenerationRequest(0, None, (), (), context.workspace)
    with pytest.raises((EvolutionError, ValueError)):
        generator(request)
    assert runtime.calls == []
    assert CandidateArchive(context.workspace).records() == []
    assert not _execution_counts(context.workspace)
