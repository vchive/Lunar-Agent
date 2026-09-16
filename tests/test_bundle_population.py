"""Real multi-file candidates through native population, evidence and resume."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.bundle_evolution import MultiFileCandidatePipeline
from famou.candidate_evaluation import inspect_candidate_evaluation
from famou.candidate_evaluation_spec import CandidateEvaluationSpec
from famou.candidate_execution import CandidateExecutionInput
from famou.evolution import (
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    PopulationStrategy,
)

MAIN_SOURCE = '''import json, os
from pathlib import Path
from helper import choose
with Path("count").open("a") as stream:
    stream.write("x")
limit = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "value").read_text())
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": choose(limit), "claimed_score": 999999}))
'''

HARNESS_SOURCE = '''import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
limit = int(Path("inputs/value").read_text())
value = json.loads(Path("output/result.json").read_text())["value"]
valid = int(type(value) is int and 0 <= value <= limit)
print(json.dumps({"schema_version": "1", "evaluator_id": "bundle-population-fixture",
    "validity": valid, "quality": float(value) if valid else None,
    "combined_score": float(value) if valid else 0.0,
    "detailed_scores": {},
    "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value exceeds the input limit."}]}))
'''


def draft_for_score(score: int, *, valid: bool = True) -> CandidateDraft:
    """A helper-only proposal; program and producer score claims are deliberately constant."""

    return CandidateDraft.from_files(
        {
            "solve/main.py": MAIN_SOURCE,
            "solve/helper.py": f"def choose(limit):\n    return {score if valid else 999}\n",
        },
        entrypoint="solve/main.py",
        metadata={"producer_score_claim": 999999},
    )


def build_context(tmp_path: Path, generate=None) -> EvolutionContext:
    """Reusable real-process fixture for the population and controller integration tests."""

    root = tmp_path.resolve()
    workspace = root / "run"
    inputs = root / "inputs"
    for directory in (workspace, inputs):
        directory.mkdir(parents=True)
    (inputs / "value").write_bytes(b"10")
    harness_path = root / "harness.py"
    harness_path.write_text(HARNESS_SOURCE, encoding="utf-8")
    harness = harness_path.read_bytes()
    python = str(Path(sys.executable).resolve())
    evaluator = CandidateEvaluationSpec(
        hashlib.sha256(harness).hexdigest(),
        len(harness),
        (python, "-I"),
        evaluator_id="bundle-population-fixture",
        timeout_seconds=3,
    )
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "bundle-population-fixture",
        "problem_type": "continuous", "statement": "Choose the largest integer within the limit.",
        "inputs": [{"path": "value", "format": "text", "fields": {"value": "integer limit"}}],
        "decision_variables": ["value"],
        "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [],
        "success_criteria": ["Value is within the limit."], "assumptions": [],
        "deliverables": ["output/result.json"],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
    })
    pipeline = MultiFileCandidatePipeline(
        evaluator=evaluator,
        harness_path=harness_path,
        input_root=inputs,
        inputs=(CandidateExecutionInput("value", "fixture", 2, hashlib.sha256(b"10").hexdigest()),),
        command=(python,),
        dependency_sha256="b" * 64,
        environment_sha256="c" * 64,
        timeout_seconds=3,
        max_output_bytes=1024,
    )
    if generate is None:
        proposals = iter((1, 2, 999, 9))

        def generate(request):
            del request
            return draft_for_score(next(proposals))

    config = pipeline.configure(EvolutionConfig(
        strategy="population", max_rounds=1, stagnation_rounds=3,
        population_size=2, offspring_per_iteration=2, num_islands=2,
        migration_interval=1, migration_rate=1.0, rng_seed=7,
        timeout_seconds=30,
    ))
    return EvolutionContext(
        contract=contract, workspace=workspace, generate=generate, evaluate=pipeline,
        config=config, bundle_pipeline=pipeline,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _reject_generate(request):
    del request
    pytest.fail("resume must validate retained evidence before generating or running candidates")


def test_native_population_ranks_helper_improvement_and_ignores_high_invalid_claim(tmp_path):
    requests = []
    proposals = iter((1, 2, 999, 9))

    def generate(request):
        requests.append(request)
        return draft_for_score(next(proposals))

    context = build_context(tmp_path, generate)
    result = PopulationStrategy(context).run()
    archive = CandidateArchive(context.workspace)
    records = archive.records()

    assert result.status == "completed"
    assert result.iterations == 1
    assert result.evaluated_candidates == 4
    assert result.valid_candidates == 3
    assert [item.evaluation.combined_score for item in records] == [1, 2, 0, 9]
    assert [item.evaluation.validity for item in records] == [1, 1, 0, 1]
    assert result.best_candidate_id == records[3].candidate_id
    assert result.best_score == 9
    assert archive.best() == records[3]
    assert len({item.source_sha256 for item in records}) == 1
    assert records[0].source_sha256 == hashlib.sha256(MAIN_SOURCE.encode()).hexdigest()
    assert len({item.bundle_evidence["bundle_sha256"] for item in records}) == 4
    assert all(item.bundle_evidence is not None for item in records)

    for candidate in records:
        source = context.workspace / candidate.code_path
        assert source.read_text() == MAIN_SOURCE
        assert (source.parent / "helper.py").is_file()
        receipt = archive.read_candidate_receipt(candidate.candidate_id, source_path=source)
        assert receipt.schema_version == "2"
        assert receipt.bundle_evidence == candidate.bundle_evidence
        evaluation = inspect_candidate_evaluation(
            context.workspace / candidate.bundle_evidence["evaluation_path"],
            expected_evaluation_sha256=candidate.bundle_evidence["evaluation_sha256"],
        )
        assert evaluation.report.combined_score == candidate.evaluation.combined_score
        assert evaluation.report.validity == candidate.evaluation.validity

    assert [item.parent_id for item in records[:2]] == [None, None]
    assert [item.island_id for item in records[:2]] == [0, 1]
    by_id = {item.candidate_id: item for item in records}
    for candidate in records[2:]:
        parent = by_id[candidate.parent_id]
        assert parent.evaluation.validity == 1
        assert candidate.generation == parent.generation + 1
        assert candidate.iteration == 1
    assert [request.iteration for request in requests] == [0, 0, 1, 1]
    assert all(request.parent.bundle_evidence for request in requests[2:])
    assert [item.code for item in archive.offspring_outcomes()] == ["evaluated", "evaluated"]
    state = archive.read_state()
    # Each island has one survivor; the existing migration rule preserves its last member.
    assert state["last_migration_iteration"] == 0
    assert state["outcome_watermark"] == 1
    assert by_id[state["best_candidate_id"]] == records[3]
    assert all(
        by_id[candidate_id].evaluation.validity == 1
        for ids in state["active_ids"].values() for candidate_id in ids
    )
    counts = list((context.workspace / "evolution" / "bundle-attempts").rglob("count"))
    assert len(counts) == 4
    assert all(path.read_text() == "x" for path in counts)


def test_multifile_migration_moves_verified_candidates_between_populated_islands(tmp_path):
    proposals = iter((1, 2, 3, 4, 8, 9))

    def generate(request):
        del request
        return draft_for_score(next(proposals))

    context = build_context(tmp_path, generate)
    context = replace(context, config=replace(context.config, population_size=4))
    result = PopulationStrategy(context).run()
    archive = CandidateArchive(context.workspace)
    records = {item.candidate_id: item for item in archive.records()}
    state = archive.read_state()

    assert result.status == "completed"
    assert result.evaluated_candidates == 6
    assert result.best_score == 9
    assert state["last_migration_iteration"] == 1
    assert len(state["active_ids"]["0"]) == len(state["active_ids"]["1"]) == 2
    assert all(
        records[candidate_id].island_id != int(island)
        for island, candidate_ids in state["active_ids"].items()
        for candidate_id in candidate_ids
    )
    assert all(candidate.bundle_evidence is not None for candidate in records.values())
    before = _files(context.workspace)
    assert PopulationStrategy(replace(context, generate=_reject_generate)).resume() == result
    assert _files(context.workspace) == before


def test_terminal_bundle_resume_is_read_only_and_never_reexecutes(tmp_path):
    context = build_context(tmp_path)
    result = PopulationStrategy(context).run()
    assert result.status == "completed"
    before = _files(context.workspace)

    resumed = PopulationStrategy(replace(context, generate=_reject_generate)).resume()

    assert resumed.to_dict() == result.to_dict()
    assert _files(context.workspace) == before


@pytest.mark.parametrize("tamper", ["helper", "evaluation_output", "receipt_binding"])
def test_resume_rejects_changed_bundle_or_evaluation_before_generation(tmp_path, tamper):
    context = build_context(tmp_path)
    assert PopulationStrategy(context).run().status == "completed"
    archive = CandidateArchive(context.workspace)
    candidate = archive.best()
    assert candidate is not None
    source = context.workspace / candidate.code_path
    if tamper == "helper":
        (source.parent / "helper.py").write_text("def choose(limit):\n    return 0\n")
    elif tamper == "evaluation_output":
        evaluation = context.workspace / candidate.bundle_evidence["evaluation_path"]
        (evaluation / "output" / "result.json").write_text('{"value": 0}')
    else:
        receipt = archive.candidate_receipt_path(candidate.candidate_id, source_path=source)
        payload = json.loads(receipt.read_bytes())
        payload["bundle_evidence"]["bundle_sha256"] = "0" * 64
        receipt.write_text(json.dumps(payload))
    before = _files(context.workspace)

    with pytest.raises(EvolutionError):
        PopulationStrategy(replace(context, generate=_reject_generate)).resume()

    assert _files(context.workspace) == before


@pytest.mark.parametrize("initial_failure", [False, True], ids=["offspring", "initial"])
def test_failed_process_retains_attempts_without_fabricating_candidate_score(tmp_path, initial_failure):
    requests = []

    def generate(request):
        requests.append(request)
        if not initial_failure and request.iteration == 0:
            return draft_for_score(len(requests))
        return CandidateDraft.from_files(
            {"solve/main.py": "raise SystemExit(7)\n", "solve/helper.py": "unused = True\n"},
            entrypoint="solve/main.py",
        )

    context = build_context(tmp_path, generate)
    result = PopulationStrategy(context).run()
    archive = CandidateArchive(context.workspace)

    assert result.status == "failed"
    assert result.iterations == 0
    assert len(archive.records()) == (0 if initial_failure else 2)
    assert result.best_score == (None if initial_failure else 2)
    assert result.evaluated_candidates == (0 if initial_failure else 2)
    attempts = list((context.workspace / "evolution" / "bundle-attempts").rglob("completed.json"))
    assert len(attempts) == (2 if initial_failure else 4)
    executions = [json.loads((path.parent / "result.json").read_bytes()) for path in attempts]
    failed = [item for item in executions if item["runner_result"]["status"] == "failed"]
    assert len(failed) == 2
    assert all(item["runner_result"]["execution"]["exit_code"] == 7 for item in failed)
    assert not any("combined_score" in json.dumps(item) for item in failed)
    outcomes = archive.offspring_outcomes()
    assert [item.code for item in outcomes] == ([] if initial_failure else ["candidate_failed"] * 2)
    assert all(item.candidate_id is None for item in outcomes)
    before = _files(context.workspace)

    resumed = PopulationStrategy(replace(context, generate=_reject_generate)).resume()

    assert resumed.to_dict() == result.to_dict()
    assert _files(context.workspace) == before


@pytest.mark.parametrize("field", ["evaluator_fingerprint", "runner_fingerprint", "dependency_sha256"])
def test_resume_rejects_changed_pipeline_authority(tmp_path, field):
    context = build_context(tmp_path)
    assert PopulationStrategy(context).run().status == "completed"
    changed = replace(context.config, **{field: "0" * 64})
    before = _files(context.workspace)

    with pytest.raises((EvolutionError, ValueError)):
        PopulationStrategy(replace(context, generate=_reject_generate, config=changed)).resume()

    assert _files(context.workspace) == before
