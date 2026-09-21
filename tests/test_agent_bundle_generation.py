"""Strict complete-source Agent proposals and verified generation contexts."""
from __future__ import annotations

import json

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.agent_bundle_generation import PrivateTree
from lunar_evolution.agent_evolution import MAX_GENERATION_PROMPT_BYTES, AgentCandidateGenerator
from lunar_evolution.agents import MAX_TEXT_BYTES, AgentResult
from lunar_evolution.evolution import (
    CandidateDraft,
    EvolutionError,
    GenerationRequest,
    PopulationStrategy,
)


class BundleFixtureAgent:
    name = "bundle-generation-fixture"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def __init__(self, callback=None):
        self.callback = callback
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        value = self.callback(request) if self.callback else {
            "entrypoint": "main.py", "files": {"main.py": "pass\n", "helper.py": "value=1\n"},
        }
        return AgentResult(self.name, request.role, json.dumps(value))

    def cancel(self):
        return None

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        del observer


def _generator(context, adapter=None):
    return AgentCandidateGenerator(
        adapter or BundleFixtureAgent(), contract=context.contract,
        bundle_pipeline=context.bundle_pipeline,
    )


@pytest.mark.parametrize("response", [
    "pass\n",
    "```json\n{}\n```",
    "[]",
    '{"files":{"main.py":"pass"}}',
    '{"entrypoint":"main.py","files":{"helper.py":"pass"}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"source":"pass"}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"combined_score":99}',
    '{"entrypoint":"main.py","entrypoint":"helper.py","files":{"main.py":"pass","helper.py":"pass"}}',
    '{"entrypoint":"main.py","files":{"main.py":"first","main.py":"second"}}',
    '{"entrypoint":"main.py","files":{"main.py":null}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"metadata":{"x":NaN}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"metadata":{"x":Infinity}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass","../escape.py":"pass"}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass","helper.py":"\\ud800"}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"metadata":{"agent_adapter":"forged"}}',
    '{"entrypoint":"main.py","files":{"main.py":"pass"},"metadata":{"seed_handoff":{}}}',
    "{}" + " " * MAX_TEXT_BYTES,
])
def test_bundle_agent_rejects_ambiguous_invalid_or_oversized_responses(tmp_path, response):
    generator = _generator(build_context(tmp_path))
    with pytest.raises((EvolutionError, ValueError)):
        generator._draft(response)
    assert not generator.adapter.requests


def test_complete_agent_response_preserves_helpers_and_experiment(tmp_path):
    generator = _generator(build_context(tmp_path))
    draft = generator._draft(json.dumps({
        "entrypoint": "solve/main.py", "files": {"solve/main.py": "pass", "solve/helper.py": "x=2"},
        "metadata": {"family": "bundle"},
        "experiment": {"schema_version": "1", "hypothesis": "A helper improvement increases quality.",
                       "change_tags": ["helper"], "target_metrics": [{"metric": "quality", "direction": "increase"}]},
    }))
    assert draft.source_files == {"solve/main.py": "pass", "solve/helper.py": "x=2"}
    assert draft.source == "pass"
    assert draft.metadata["agent_adapter"] == generator.adapter.name
    assert draft.metadata["experiment"]["change_tags"] == ["helper"]


def test_bundle_mode_rejects_legacy_staging_and_requires_contract(tmp_path):
    context = build_context(tmp_path)
    with pytest.raises(TypeError):
        AgentCandidateGenerator(BundleFixtureAgent(), bundle_pipeline=context.bundle_pipeline)
    # Even an invalid legacy object must not be accepted as a parallel input path.
    with pytest.raises((TypeError, ValueError)):
        AgentCandidateGenerator(BundleFixtureAgent(), contract=context.contract,
                                bundle_pipeline=context.bundle_pipeline, inputs=(object(),))


def _parent(context, draft=None):
    strategy = PopulationStrategy(context)
    return strategy._persist(
        draft or draft_for_score(1), iteration=0, generation=0, parent=None, island_id=0,
    )


def test_large_parent_uses_complete_file_references_and_preserves_every_helper(tmp_path):
    context = build_context(tmp_path)
    files = {**draft_for_score(1).source_files,
             **{f"library/helper{i}.py": "# " + str(i) + "x" * 3000 + "\n" for i in range(40)}}
    parent = _parent(context, CandidateDraft.from_files(files, "solve/main.py"))

    def revise(request):
        assert len(request.prompt.encode("utf-8")) <= MAX_GENERATION_PROMPT_BYTES
        assert '"context_file"' in request.prompt
        value = json.loads((request.workspace / "context/context.json").read_bytes())
        source = value["parent"]["source"]
        assert source["file_count"] == len(files)
        complete = json.loads((request.workspace / source["files_path"]).read_bytes())
        assert complete == files
        for name, text in complete.items():
            assert (request.workspace / source["root"] / name).read_text() == text
        complete["solve/helper.py"] = "def choose(limit):\n    return 2\n"
        return {"entrypoint": "solve/main.py", "files": complete}

    generator = _generator(context, BundleFixtureAgent(revise))
    revised = generator(GenerationRequest(1, parent, (), (parent,), context.workspace))
    assert set(revised.source_files) == set(files)
    assert revised.source_files["library/helper39.py"] == files["library/helper39.py"]
    assert "return 2" in revised.source_files["solve/helper.py"]


@pytest.mark.parametrize("drift", ["original_input", "harness", "parent_source", "context_input", "context_source"])
def test_observed_generation_inputs_and_sources_cannot_change_during_agent_call(tmp_path, drift):
    context = build_context(tmp_path)
    parent = _parent(context)

    def change(request):
        targets = {
            "original_input": context.bundle_pipeline.input_root / "value",
            "harness": context.bundle_pipeline.harness_path,
            "parent_source": (context.workspace / parent.code_path).with_name("helper.py"),
            "context_input": request.workspace / "context/inputs/value",
            "context_source": request.workspace / "context/parent/source/solve/helper.py",
        }
        targets[drift].write_text("changed")
        return {"entrypoint": "main.py", "files": {"main.py": "pass"}}

    generator = _generator(context, BundleFixtureAgent(change))
    with pytest.raises((EvolutionError, ValueError)):
        generator(GenerationRequest(1, parent, (), (parent,), context.workspace))
    assert len(generator.adapter.requests) == 1


@pytest.mark.parametrize("drift", ["source", "receipt", "evaluation"])
def test_parent_evidence_drift_is_rejected_before_agent_invocation(tmp_path, drift):
    context = build_context(tmp_path)
    parent = _parent(context)
    source = context.workspace / parent.code_path
    targets = {
        "source": source.with_name("helper.py"), "receipt": source.with_name("receipt.json"),
        "evaluation": context.workspace / parent.bundle_evidence["evaluation_path"] / "output/result.json",
    }
    targets[drift].write_text("changed")
    generator = _generator(context)
    with pytest.raises((EvolutionError, ValueError)):
        generator(GenerationRequest(1, parent, (), (parent,), context.workspace))
    assert not generator.adapter.requests


def test_single_file_agent_draft_wire_behavior_is_unchanged():
    generator = AgentCandidateGenerator(BundleFixtureAgent())
    plain = generator._draft("pass\n")
    structured = generator._draft('{"source":"pass\\n","filename":"legacy.py","metadata":{"family":"old"}}')
    assert plain.source == "pass" and plain.source_files is None
    assert structured.filename == "legacy.py" and structured.source_files is None
    assert structured.metadata == {"family": "old", "agent_adapter": generator.adapter.name}


def test_interruption_survives_generation_tree_close_failure(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    armed = False
    original_close = PrivateTree.close

    def interrupt(request):
        nonlocal armed
        armed = True
        raise KeyboardInterrupt

    def close(tree):
        original_close(tree)
        if armed:
            raise OSError("fixture close failure")

    monkeypatch.setattr(PrivateTree, "close", close)
    generator = _generator(context, BundleFixtureAgent(interrupt))
    with pytest.raises(KeyboardInterrupt):
        generator(GenerationRequest(0, None, (), (), context.workspace))


@pytest.mark.parametrize("changed", ["contract", "pipeline"])
def test_generator_profile_changes_fail_before_agent_call(tmp_path, changed):
    context = build_context(tmp_path)
    generator = _generator(context)
    if changed == "contract":
        context.contract.inputs[0].fields["value"] = "changed after generator construction"
    else:
        context.bundle_pipeline.command = (*context.bundle_pipeline.command, "-I")
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(0, None, (), (), context.workspace))
    assert not generator.adapter.requests
