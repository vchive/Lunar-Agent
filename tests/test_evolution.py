import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import famou.evolution as evolution_module
from famou.algorithm import AlgorithmProblemContract
from famou.evolution import (
    CandidateArchive,
    CandidateDraft,
    CandidateExecution,
    CommandCandidateEvaluator,
    CommandCandidateRunner,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    EvolutionStrategy,
    ExecutionAwareCandidateEvaluator,
    LoopStrategy,
    OpenEvolveStrategy,
    PopulationState,
    PopulationStrategy,
    WorkerUnknownError,
    build_strategy,
)
from famou.openevolve_handoff import (
    declared_protocol_environment_sha256,
    source_only_dependency_sha256,
)
from famou.seed_handoff import admit_seed_manifest

SEED_EVALUATOR_SHA = "a" * 64
SEED_DEPENDENCY_SHA = "b" * 64
SEED_ENVIRONMENT_SHA = "c" * 64
SEED_PRODUCER_SHA = "d" * 64


def _contract(strategy: str = "population") -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "evolution-fixture",
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
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
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {"strategy": strategy, "max_rounds": 5, "stagnation_rounds": 3},
        }
    )


def _report(score: float, valid: int = 1) -> dict[str, object]:
    return {
        "schema_version": "1",
        "evaluator_id": "fixture",
        "validity": valid,
        "quality": score if valid else None,
        "combined_score": score if valid else 0,
        "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
        "error_info": [] if valid else [{"code": "invalid", "message": "fixture candidate is invalid"}],
    }


def _seed_manifest(
    root: Path,
    contract: AlgorithmProblemContract,
    sources: dict[str, str],
    *,
    producer_run_id: str = "run-001",
    evaluator_sha256: str = SEED_EVALUATOR_SHA,
    dependency_sha256: str = SEED_DEPENDENCY_SHA,
    environment_sha256: str = SEED_ENVIRONMENT_SHA,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        records.append(
            {
                "source_path": name,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "lineage": [],
                "provenance": {
                    "origin_kind": "external",
                    "producer_id": "openevolve",
                    "producer_fingerprint": SEED_PRODUCER_SHA,
                    "producer_run_id": producer_run_id,
                    "material_refs": [],
                    "external_evidence": {"external_score": 99.0},
                },
                "metadata": {},
            }
        )
    payload = {
        "schema_version": "1",
        "contract_sha256": contract.digest(),
        "evaluator": {"kind": "exact_harness", "fingerprint": evaluator_sha256},
        "dependency_sha256": dependency_sha256,
        "environment_sha256": environment_sha256,
        "seeds": records,
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def _admitted_initial_seeds(
    manifest: Path,
    contract: AlgorithmProblemContract,
    *,
    num_islands: int,
    evaluator_sha256: str = SEED_EVALUATOR_SHA,
    dependency_sha256: str = SEED_DEPENDENCY_SHA,
    environment_sha256: str = SEED_ENVIRONMENT_SHA,
):
    return admit_seed_manifest(
        manifest,
        contract,
        lambda path, supplied: _report(
            float(path.read_text(encoding="utf-8").split("=")[1].strip())
        ),
        evaluator_kind="exact_harness",
        evaluator_fingerprint=evaluator_sha256,
        dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
        num_islands=num_islands,
    ).admitted


def _write_controller_contract(
    workspace: Path, contract: AlgorithmProblemContract
) -> bytes:
    content = (
        json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    ).encode("utf-8")
    root = workspace / "evolution"
    root.mkdir(parents=True)
    (root / "contract.json").write_bytes(content)
    return content


def test_population_archives_every_round_and_returns_best_so_far(tmp_path: Path) -> None:
    scores = iter([0.2, 0.9, 0.4])

    def generate(request):
        return CandidateDraft(f"# round {request.iteration}\nscore = {request.iteration}\n")

    def evaluate(path, contract):
        del contract
        return _report(next(scores))

    context = EvolutionContext(
        _contract(), tmp_path, generate, evaluate,
        EvolutionConfig(max_rounds=2, stagnation_rounds=10, population_size=1),
    )
    result = PopulationStrategy(context).run()
    assert result.status == "completed"
    assert result.evaluated_candidates == 3
    assert result.best_score == 0.9
    assert result.best_candidate_id == "candidate-0002"
    assert result.best_candidate_path == "evolution/candidates/candidate-0002/candidate.py"
    assert (tmp_path / result.best_candidate_path).is_file()
    assert len((tmp_path / "evolution" / "archive.jsonl").read_text().splitlines()) == 3
    assert json.loads((tmp_path / "evolution" / "state.json").read_text())["status"] == "completed"


def test_population_persists_one_typed_outcome_for_every_offspring_attempt(
    tmp_path: Path,
) -> None:
    secret = "sk-super-secret-outcome-detail"
    offspring_calls = 0

    def generate(request):
        nonlocal offspring_calls
        if request.iteration == 0:
            return CandidateDraft("phase = 'initial'\n")
        attempt = offspring_calls
        offspring_calls += 1
        if attempt == 0:
            raise RuntimeError(secret)
        return CandidateDraft(f"attempt = {attempt}\n")

    def evaluate(path, contract):
        del contract
        source = path.read_text(encoding="utf-8")
        if "initial" in source:
            return _report(1)
        attempt = int(source.split("=")[1].strip())
        if attempt == 1:
            return _report(2)
        if attempt == 2:
            raise TimeoutError(secret)
        if attempt == 3:
            try:
                raise TimeoutError(secret)
            except TimeoutError as exc:
                raise WorkerUnknownError(secret) from exc
        raise RuntimeError(secret)

    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            generate,
            evaluate,
            EvolutionConfig(
                max_rounds=1,
                stagnation_rounds=10,
                population_size=1,
                offspring_per_iteration=5,
            ),
        )
    ).run()

    outcomes_path = tmp_path / "evolution" / "offspring-outcomes.jsonl"
    outcome_text = outcomes_path.read_text(encoding="utf-8")
    outcomes = [json.loads(line) for line in outcome_text.splitlines()]
    assert result.status == "completed"
    assert result.iterations == 1
    assert [item["code"] for item in outcomes] == [
        "candidate_failed",
        "evaluated",
        "evaluator_timeout",
        "worker_unknown",
        "run_failed",
    ]
    assert [item["attempt"] for item in outcomes] == list(range(5))
    assert all(
        set(item)
        == {
            "schema_version",
            "iteration",
            "attempt",
            "island_id",
            "code",
            "candidate_id",
        }
        for item in outcomes
    )
    assert secret not in outcome_text
    records = CandidateArchive(tmp_path).records()
    assert len(records) == 2
    assert outcomes[1]["candidate_id"] == records[1].candidate_id
    assert all("evaluation_error" not in item.metadata for item in records)
    state = json.loads((tmp_path / "evolution" / "state.json").read_text())
    assert state["outcome_schema_version"] == "1"
    assert state["outcome_start_iteration"] == 1
    assert state["outcome_watermark"] == 1
    assert len(state["outcome_watermark_sha256"]) == 64
    assert len(state["outcome_archive_baseline_sha256"]) == 64


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("candidate", "candidate_failed"),
        ("timeout", "evaluator_timeout"),
        ("worker", "worker_unknown"),
        ("run", "run_failed"),
    ],
)
def test_population_failed_only_batch_does_not_advance_iteration(
    tmp_path: Path,
    failure_kind: str,
    expected_code: str,
) -> None:
    offspring_calls = 0

    def generate(request):
        nonlocal offspring_calls
        if request.iteration == 0:
            return CandidateDraft("phase = 'initial'\n")
        offspring_calls += 1
        if failure_kind == "candidate":
            raise RuntimeError("candidate detail must remain private")
        return CandidateDraft("phase = 'offspring'\n")

    def evaluate(path, contract):
        del contract
        if "initial" in path.read_text(encoding="utf-8"):
            return _report(10)
        if failure_kind == "timeout":
            raise TimeoutError("timeout detail must remain private")
        if failure_kind == "worker":
            raise WorkerUnknownError("worker detail must remain private")
        raise RuntimeError("run detail must remain private")

    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            generate,
            evaluate,
            EvolutionConfig(
                max_rounds=1,
                stagnation_rounds=10,
                population_size=1,
                offspring_per_iteration=1,
            ),
        )
    ).run()

    state = json.loads((tmp_path / "evolution" / "state.json").read_text())
    outcomes = CandidateArchive(tmp_path).offspring_outcomes()
    assert result.status == "failed"
    assert result.iterations == 0
    assert result.best_score == 10
    assert result.error == "offspring_batch_failed"
    assert offspring_calls == 1
    assert len(CandidateArchive(tmp_path).records()) == 1
    assert [item.code for item in outcomes] == [expected_code]
    assert state["status"] == "failed"
    assert state["iteration"] == 0
    assert state["outcome_watermark"] == 0
    assert state["failed_offspring_iteration"] == 1
    assert "pending_offspring" not in state


def test_population_counts_structured_invalid_evaluation_as_evaluated(
    tmp_path: Path,
) -> None:
    def generate(request):
        return CandidateDraft(f"iteration = {request.iteration}\n")

    def evaluate(path, contract):
        del contract
        iteration = int(path.read_text(encoding="utf-8").split("=")[1].strip())
        return _report(10 if iteration == 0 else 99, valid=1 if iteration == 0 else 0)

    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            generate,
            evaluate,
            EvolutionConfig(max_rounds=1, population_size=1),
        )
    ).run()

    archive = CandidateArchive(tmp_path)
    records = archive.records()
    state = archive.read_state()
    assert result.status == "completed"
    assert result.iterations == 1
    assert result.best_candidate_id == records[0].candidate_id
    assert records[1].evaluation.validity == 0
    assert [item.code for item in archive.offspring_outcomes()] == ["evaluated"]
    assert records[1].candidate_id not in state["active_ids"]["0"]
    assert state["outcome_watermark"] == 1


def test_population_resume_rejects_an_incomplete_durable_batch_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate_calls = 0
    evaluate_calls = 0

    def generate(request):
        nonlocal generate_calls
        generate_calls += 1
        return CandidateDraft(f"iteration = {request.iteration}\ncall = {generate_calls}\n")

    def evaluate(path, contract):
        nonlocal evaluate_calls
        del path, contract
        evaluate_calls += 1
        return _report(float(evaluate_calls))

    config = EvolutionConfig(
        max_rounds=1,
        stagnation_rounds=10,
        population_size=1,
        offspring_per_iteration=2,
    )
    original_append = CandidateArchive.append_offspring_outcome
    append_calls = 0

    def append_then_crash(self, outcome):
        nonlocal append_calls
        original_append(self, outcome)
        append_calls += 1
        if append_calls == 1:
            raise RuntimeError("simulated crash after durable outcome")

    monkeypatch.setattr(CandidateArchive, "append_offspring_outcome", append_then_crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        PopulationStrategy(
            EvolutionContext(_contract(), tmp_path, generate, evaluate, config)
        ).run()

    state_path = tmp_path / "evolution" / "state.json"
    archive_path = tmp_path / "evolution" / "archive.jsonl"
    outcomes_path = tmp_path / "evolution" / "offspring-outcomes.jsonl"
    before = (state_path.read_bytes(), archive_path.read_bytes(), outcomes_path.read_bytes())
    state = json.loads(before[0])
    assert state["iteration"] == 0
    assert state["pending_offspring"]["iteration"] == 1
    assert len(before[2].splitlines()) == 1
    calls_before_resume = (generate_calls, evaluate_calls)

    def must_not_generate(request):
        pytest.fail(f"resume replayed generation for iteration {request.iteration}")

    def must_not_evaluate(path, contract):
        del path, contract
        pytest.fail("resume replayed evaluation")

    with pytest.raises(EvolutionError, match="population_iteration_incomplete"):
        PopulationStrategy(
            EvolutionContext(
                _contract(),
                tmp_path,
                must_not_generate,
                must_not_evaluate,
                config,
            )
        ).resume()

    assert (generate_calls, evaluate_calls) == calls_before_resume
    assert before == (
        state_path.read_bytes(),
        archive_path.read_bytes(),
        outcomes_path.read_bytes(),
    )


def test_population_resume_finalizes_complete_outcomes_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate_calls = 0
    evaluate_calls = 0

    def generate(request):
        nonlocal generate_calls
        generate_calls += 1
        return CandidateDraft(f"iteration = {request.iteration}\ncall = {generate_calls}\n")

    def evaluate(path, contract):
        nonlocal evaluate_calls
        del path, contract
        evaluate_calls += 1
        return _report(float(evaluate_calls))

    config = EvolutionConfig(
        max_rounds=1,
        stagnation_rounds=10,
        population_size=1,
        offspring_per_iteration=2,
    )
    original_write = CandidateArchive.write_state

    def crash_before_final_state(self, payload):
        if (
            payload.get("status") == "running"
            and payload.get("iteration") == 1
            and payload.get("outcome_watermark") == 1
        ):
            raise RuntimeError("simulated crash before final state")
        original_write(self, payload)

    monkeypatch.setattr(CandidateArchive, "write_state", crash_before_final_state)
    with pytest.raises(RuntimeError, match="simulated crash"):
        PopulationStrategy(
            EvolutionContext(_contract(), tmp_path, generate, evaluate, config)
        ).run()
    state_path = tmp_path / "evolution" / "state.json"
    archive_path = tmp_path / "evolution" / "archive.jsonl"
    outcomes_path = tmp_path / "evolution" / "offspring-outcomes.jsonl"
    pending = json.loads(state_path.read_text(encoding="utf-8"))
    assert pending["iteration"] == 0
    assert pending["pending_offspring"]["iteration"] == 1
    assert len(outcomes_path.read_text(encoding="utf-8").splitlines()) == 2
    durable_before_resume = (archive_path.read_bytes(), outcomes_path.read_bytes())
    calls_before_resume = (generate_calls, evaluate_calls)

    monkeypatch.setattr(CandidateArchive, "write_state", original_write)
    resumed = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: pytest.fail("complete resume replayed generation"),
            lambda path, contract: pytest.fail("complete resume replayed evaluation"),
            config,
        )
    ).resume()

    assert resumed.status == "completed"
    assert resumed.iterations == 1
    assert (generate_calls, evaluate_calls) == calls_before_resume
    assert durable_before_resume == (
        archive_path.read_bytes(),
        outcomes_path.read_bytes(),
    )
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["iteration"] == 1
    assert final_state["outcome_watermark"] == 1
    assert "pending_offspring" not in final_state


@pytest.mark.parametrize(
    "tamper",
    [
        "drop_outcome",
        "change_failure_code",
        "swap_candidates",
        "orphan_candidate",
        "baseline_candidate",
        "foreign_candidate",
        "watermark",
    ],
)
def test_population_resume_fails_closed_on_outcome_binding_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    config = EvolutionConfig(
        max_rounds=1,
        stagnation_rounds=10,
        population_size=1,
        offspring_per_iteration=3,
    )

    offspring_calls = 0

    def generate(request):
        nonlocal offspring_calls
        if request.iteration > 0:
            offspring_calls += 1
            if offspring_calls == 1:
                raise RuntimeError("controlled candidate failure")
        return CandidateDraft(f"iteration = {request.iteration}\n")

    PopulationStrategy(
        EvolutionContext(
            _contract(), tmp_path, generate, lambda path, contract: _report(1), config
        )
    ).run()
    archive = CandidateArchive(tmp_path)
    outcomes_path = archive.offspring_outcomes_path
    outcome_lines = [
        json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines()
    ]
    if tamper == "drop_outcome":
        outcome_lines.pop()
        outcomes_path.write_text(
            "".join(json.dumps(item) + "\n" for item in outcome_lines),
            encoding="utf-8",
        )
    elif tamper == "change_failure_code":
        assert outcome_lines[0]["code"] == "candidate_failed"
        outcome_lines[0]["code"] = "worker_unknown"
        outcomes_path.write_text(
            "".join(json.dumps(item) + "\n" for item in outcome_lines),
            encoding="utf-8",
        )
    elif tamper == "swap_candidates":
        outcome_lines[1]["candidate_id"], outcome_lines[2]["candidate_id"] = (
            outcome_lines[2]["candidate_id"],
            outcome_lines[1]["candidate_id"],
        )
        outcomes_path.write_text(
            "".join(json.dumps(item) + "\n" for item in outcome_lines),
            encoding="utf-8",
        )
    elif tamper == "orphan_candidate":
        archive.persist(
            CandidateDraft("orphan = True\n"),
            strategy="population",
            iteration=1,
            generation=1,
            parent_id=archive.records()[0].candidate_id,
            island_id=0,
            evaluation=evolution_module._report(_report(3)),
        )
    elif tamper == "baseline_candidate":
        archive.persist(
            CandidateDraft("baseline_orphan = True\n"),
            strategy="population",
            iteration=0,
            generation=0,
            island_id=0,
            evaluation=evolution_module._report(_report(100)),
        )
    elif tamper == "foreign_candidate":
        archive.persist(
            CandidateDraft("foreign = True\n"),
            strategy="openevolve",
            iteration=1,
            generation=1,
            island_id=None,
            evaluation=evolution_module._report(_report(100)),
        )
    else:
        state = archive.read_state()
        state["outcome_watermark"] = 0
        archive.write_state(state)

    with pytest.raises(EvolutionError, match="population_outcome_state_mismatch"):
        PopulationStrategy(
            EvolutionContext(
                _contract(),
                tmp_path,
                lambda request: pytest.fail("tampered resume generated a candidate"),
                lambda path, contract: pytest.fail("tampered resume evaluated a candidate"),
                config,
            )
        ).resume()


def test_public_strategy_and_population_state_contracts_are_json_safe() -> None:
    state = PopulationState(
        iteration=2,
        population_size=4,
        offspring_per_iteration=1,
        num_islands=2,
        active_ids={"0": ("candidate-0001",), "1": ("candidate-0002",)},
        best_candidate_id="candidate-0002",
        rng_seed=7,
        last_migration_iteration=2,
    )
    assert state.to_dict()["active_ids"]["1"] == ["candidate-0002"]
    assert isinstance(PopulationStrategy, type)
    assert hasattr(EvolutionStrategy, "run")
    assert (
        EvolutionContext(
            _contract(),
            Path("."),
            lambda request: CandidateDraft("unused"),
            lambda path, contract: _report(1),
        ).initial_seeds
        == ()
    )


def test_population_atomically_commits_verified_initial_seeds_before_offspring(
    tmp_path: Path,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    workspace = tmp_path / "workspace"
    generated = []
    evaluated = []

    def generate(request):
        generated.append(request)
        assert {item.candidate_id for item in request.archive} >= {
            seed.candidate_id for seed in seeds
        }
        return CandidateDraft("score = 3\n")

    def evaluate(path, supplied_contract):
        assert supplied_contract == contract
        evaluated.append(path)
        return _report(3)

    result = PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            generate,
            evaluate,
            EvolutionConfig(
                max_rounds=1,
                stagnation_rounds=10,
                population_size=2,
                offspring_per_iteration=1,
                num_islands=2,
                evaluator_fingerprint=SEED_EVALUATOR_SHA,
            ),
            initial_seeds=seeds,
        )
    ).run()

    assert result.status == "completed"
    assert result.evaluated_candidates == 3
    assert len(generated) == 1
    assert [path.parent.name for path in evaluated] == ["candidate-0001"]
    archive = CandidateArchive(workspace).records()
    archived_seeds = [item for item in archive if item.candidate_id.startswith("seed-")]
    assert {item.candidate_id for item in archived_seeds} == {
        seed.candidate_id for seed in seeds
    }
    assert all(item.generation == item.iteration == 0 for item in archived_seeds)
    assert all(item.parent_id is None for item in archived_seeds)

    root = workspace / "evolution"
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    summary = state["seed_admission"]
    assert set(summary) == {"schema_version", "seeds", "admission_sha256"}
    assert all(
        set(item)
        == {
            "candidate_id",
            "receipt_sha256",
            "handoff_sha256",
            "provenance_sha256",
        }
        for item in summary["seeds"]
    )
    marker = json.loads((root / "seed-commit.json").read_text(encoding="utf-8"))
    assert marker["candidate_ids"] == sorted(seed.candidate_id for seed in seeds)
    assert marker["admission_sha256"] == summary["admission_sha256"]
    for seed in seeds:
        candidate_dir = root / "candidates" / seed.candidate_id
        assert (candidate_dir / seed.draft.filename).read_text(encoding="utf-8") == seed.draft.source
        assert json.loads((candidate_dir / "receipt.json").read_text(encoding="utf-8")) == seed.receipt.to_dict()
        record = json.loads((candidate_dir / "record.json").read_text(encoding="utf-8"))
        assert record["candidate_id"] == seed.candidate_id
        assert record["seed_handoff_evidence"]["handoff_sha256"] == seed.handoff_sha256


def test_population_seed_commit_preserves_controller_contract_bytes(
    tmp_path: Path,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"candidate.py": "score = 1\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)

    result = PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            EvolutionConfig(
                max_rounds=1,
                population_size=1,
                evaluator_fingerprint=SEED_EVALUATOR_SHA,
            ),
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()

    root = workspace / "evolution"
    assert result.status == "cancelled"
    assert (root / "contract.json").read_bytes() == contract_content
    assert {path.name for path in root.iterdir()} == {
        "archive.jsonl",
        "candidates",
        "contract.json",
        "seed-commit.json",
        "state.json",
    }
    assert not (workspace / ".evolution-seed-stage-v1").exists()
    assert not (workspace / ".evolution-seed-backup-v1").exists()


def test_population_seed_publish_failure_restores_controller_contract_only_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"candidate.py": "score = 1\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)
    root = workspace / "evolution"
    stage = workspace / ".evolution-seed-stage-v1"
    real_replace = os.replace
    failed = False
    observed = []

    def fail_stage_publish(source, destination):
        nonlocal failed
        if not failed and Path(source) == stage and Path(destination) == root:
            failed = True
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(evolution_module.os, "replace", fail_stage_publish)
    context = EvolutionContext(
        contract,
        workspace,
        lambda request: pytest.fail("failed seed commit generated offspring"),
        lambda path, supplied: pytest.fail("failed seed commit evaluated a candidate"),
        EvolutionConfig(
            max_rounds=1,
            population_size=1,
            evaluator_fingerprint=SEED_EVALUATOR_SHA,
        ),
        observe=lambda event, payload: observed.append((event, payload)),
        initial_seeds=seeds,
    )

    with pytest.raises(EvolutionError, match="^verified_seed_commit_failed$"):
        PopulationStrategy(context).run()

    assert failed
    assert {path.name for path in root.iterdir()} == {"contract.json"}
    assert (root / "contract.json").read_bytes() == contract_content
    assert not (root / "archive.jsonl").exists()
    assert not stage.exists()
    assert not (workspace / ".evolution-seed-backup-v1").exists()
    assert observed == []


@pytest.mark.parametrize("retain_stage", [True, False])
def test_candidate_archive_recovers_interrupted_controller_seed_publish(
    tmp_path: Path, retain_stage: bool
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"candidate.py": "score = 1\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
    )
    PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            config,
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()
    root = workspace / "evolution"
    stage = workspace / ".evolution-seed-stage-v1"
    backup = workspace / ".evolution-seed-backup-v1"

    os.replace(root, stage)
    _write_controller_contract(workspace, contract)
    os.replace(root, backup)
    if not retain_stage:
        shutil.rmtree(stage)
    assert not root.exists()

    recovered = CandidateArchive(workspace)

    assert recovered.root == root
    assert {path.name for path in root.iterdir()} == {"contract.json"}
    assert (root / "contract.json").read_bytes() == contract_content
    assert not stage.exists()
    assert not backup.exists()


def test_candidate_archive_finishes_cleanup_after_seed_publish_crash(
    tmp_path: Path,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"candidate.py": "score = 1\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)
    PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            EvolutionConfig(
                max_rounds=1,
                population_size=1,
                evaluator_fingerprint=SEED_EVALUATOR_SHA,
            ),
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()
    root = workspace / "evolution"
    backup = workspace / ".evolution-seed-backup-v1"
    backup.mkdir()
    (backup / "contract.json").write_bytes(contract_content)
    archive_before = (root / "archive.jsonl").read_bytes()

    recovered = CandidateArchive(workspace)

    assert [item.candidate_id for item in recovered.records()] == [seeds[0].candidate_id]
    assert (root / "archive.jsonl").read_bytes() == archive_before
    assert (root / "contract.json").read_bytes() == contract_content
    assert not backup.exists()


@pytest.mark.parametrize("invalid_root", ["extra", "noncanonical", "symlink"])
def test_population_seed_commit_rejects_noncanonical_controller_root(
    tmp_path: Path, invalid_root: str
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"candidate.py": "score = 1\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)
    root = workspace / "evolution"
    contract_path = root / "contract.json"
    if invalid_root == "extra":
        (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        expected = "verified_seed_initialization_requires_empty_archive"
    elif invalid_root == "noncanonical":
        contract_path.write_bytes(contract_content.rstrip())
        expected = "verified_seed_contract_invalid"
    else:
        outside = workspace / "outside-contract.json"
        outside.write_bytes(contract_content)
        contract_path.unlink()
        contract_path.symlink_to(outside)
        expected = "verified_seed_contract_invalid"

    with pytest.raises(EvolutionError, match=f"^{expected}$"):
        PopulationStrategy(
            EvolutionContext(
                contract,
                workspace,
                lambda request: pytest.fail("invalid root generated offspring"),
                lambda path, supplied: pytest.fail("invalid root evaluated a candidate"),
                EvolutionConfig(
                    max_rounds=1,
                    population_size=1,
                    evaluator_fingerprint=SEED_EVALUATOR_SHA,
                ),
                initial_seeds=seeds,
            )
        ).run()

    assert not (root / "archive.jsonl").exists()
    assert not (workspace / ".evolution-seed-stage-v1").exists()
    assert not (workspace / ".evolution-seed-backup-v1").exists()


def test_candidate_archive_rejects_ambiguous_or_unsafe_seed_recovery_state(
    tmp_path: Path,
) -> None:
    contract = _contract()
    workspace = tmp_path / "workspace"
    contract_content = _write_controller_contract(workspace, contract)
    root = workspace / "evolution"
    backup = workspace / ".evolution-seed-backup-v1"
    backup.mkdir()
    (backup / "contract.json").write_bytes(contract_content)
    (backup / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    os.replace(root, workspace / ".evolution-seed-stage-v1")

    with pytest.raises(EvolutionError, match="^verified_seed_recovery_ambiguous$"):
        CandidateArchive(workspace)

    shutil.rmtree(backup)
    unsafe_target = workspace / "unsafe-backup"
    unsafe_target.mkdir()
    backup.symlink_to(unsafe_target, target_is_directory=True)
    with pytest.raises(EvolutionError, match="^verified_seed_recovery_ambiguous$"):
        CandidateArchive(workspace)

    ambiguous_workspace = tmp_path / "ambiguous-workspace"
    ambiguous_content = _write_controller_contract(ambiguous_workspace, contract)
    ambiguous_backup = ambiguous_workspace / ".evolution-seed-backup-v1"
    ambiguous_backup.mkdir()
    (ambiguous_backup / "contract.json").write_bytes(ambiguous_content)
    (ambiguous_workspace / ".evolution-seed-stage-v1").mkdir(mode=0o700)
    with pytest.raises(EvolutionError, match="^verified_seed_recovery_ambiguous$"):
        CandidateArchive(ambiguous_workspace)


def test_population_seed_commit_failure_leaves_no_visible_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    workspace = tmp_path / "workspace"
    generated = []
    evaluated = []
    observed = []
    real_replace = os.replace

    def fail_publish(source, destination):
        if Path(destination) == workspace / "evolution":
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(evolution_module.os, "replace", fail_publish)
    context = EvolutionContext(
        contract,
        workspace,
        lambda request: generated.append(request) or CandidateDraft("score = 3\n"),
        lambda path, supplied: evaluated.append(path) or _report(3),
        EvolutionConfig(
            max_rounds=1,
            population_size=2,
            num_islands=2,
            evaluator_fingerprint=SEED_EVALUATOR_SHA,
        ),
        observe=lambda event, payload: observed.append((event, payload)),
        initial_seeds=seeds,
    )

    with pytest.raises(EvolutionError, match="^verified_seed_commit_failed$"):
        PopulationStrategy(context).run()

    assert not (workspace / "evolution").exists()
    assert list(workspace.glob(".evolution-seed-stage-*")) == []
    assert generated == []
    assert evaluated == []
    assert observed == []


def test_population_rejects_verified_seed_batch_over_capacity_without_mutation(
    tmp_path: Path,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    generated = []
    evaluated = []
    context = EvolutionContext(
        contract,
        workspace,
        lambda request: generated.append(request) or CandidateDraft("score = 3\n"),
        lambda path, supplied: evaluated.append(path) or _report(3),
        EvolutionConfig(
            max_rounds=1,
            population_size=1,
            evaluator_fingerprint=SEED_EVALUATOR_SHA,
        ),
        initial_seeds=seeds,
    )

    with pytest.raises(
        EvolutionError, match="^verified_seed_population_capacity_exceeded$"
    ):
        PopulationStrategy(context).run()

    assert not (workspace / "evolution").exists()
    assert generated == []
    assert evaluated == []


def test_population_seeded_resume_revalidates_unchanged_admissions(
    tmp_path: Path,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    workspace = tmp_path / "workspace"
    config = EvolutionConfig(
        max_rounds=1,
        population_size=2,
        num_islands=2,
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
    )
    first = PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            config,
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()
    assert first.status == "cancelled"
    archive_path = workspace / "evolution" / "archive.jsonl"
    state_path = workspace / "evolution" / "state.json"
    before = (archive_path.read_bytes(), state_path.read_bytes())

    fresh_seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    resumed = PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("terminal resume generated offspring"),
            lambda path, supplied: pytest.fail("terminal resume evaluated a candidate"),
            config,
            initial_seeds=fresh_seeds,
        )
    ).resume()

    assert resumed.status == "cancelled"
    assert (archive_path.read_bytes(), state_path.read_bytes()) == before


def test_population_seeded_resume_requires_fresh_admissions(tmp_path: Path) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    workspace = tmp_path / "workspace"
    config = EvolutionConfig(
        max_rounds=1,
        population_size=2,
        num_islands=2,
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
    )
    PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            config,
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()
    archive_path = workspace / "evolution" / "archive.jsonl"
    state_path = workspace / "evolution" / "state.json"
    before = (archive_path.read_bytes(), state_path.read_bytes())

    with pytest.raises(
        EvolutionError, match="^verified_seed_resume_requires_initial_seeds$"
    ):
        PopulationStrategy(
            EvolutionContext(
                contract,
                workspace,
                lambda request: pytest.fail("resume generated offspring"),
                lambda path, supplied: pytest.fail("resume evaluated a candidate"),
                config,
            )
        ).resume()

    assert (archive_path.read_bytes(), state_path.read_bytes()) == before


@pytest.mark.parametrize(
    ("tamper_target", "expected_error"),
    [
        ("source", "verified_seed_resume_mismatch"),
        ("receipt", "verified_seed_resume_mismatch"),
        ("record", "verified_seed_resume_mismatch"),
        ("marker", "verified_seed_resume_mismatch"),
        ("active", "population state references an unknown candidate"),
    ],
)
def test_population_seeded_resume_rejects_tampered_transaction(
    tmp_path: Path, tamper_target: str, expected_error: str
) -> None:
    contract = _contract()
    manifest = _seed_manifest(
        tmp_path / "incoming",
        contract,
        {"first.py": "score = 1\n", "second.py": "score = 2\n"},
    )
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    workspace = tmp_path / "workspace"
    config = EvolutionConfig(
        max_rounds=1,
        population_size=2,
        num_islands=2,
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
    )
    PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            config,
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()
    fresh_seeds = _admitted_initial_seeds(manifest, contract, num_islands=2)
    root = workspace / "evolution"
    seed = fresh_seeds[0]
    candidate_dir = root / "candidates" / seed.candidate_id
    target = {
        "source": candidate_dir / seed.draft.filename,
        "receipt": candidate_dir / "receipt.json",
        "record": candidate_dir / "record.json",
        "marker": root / "seed-commit.json",
        "active": root / "state.json",
    }[tamper_target]
    if tamper_target == "source":
        target.write_text("score = 999\n", encoding="utf-8")
    else:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if tamper_target == "receipt":
            payload["combined_score"] = 999
        elif tamper_target == "record":
            payload["seed_handoff_evidence"]["provenance"]["producer_run_id"] = "run-tampered"
        elif tamper_target == "marker":
            payload["candidate_ids"] = []
        else:
            island = next(key for key, values in payload["active_ids"].items() if values)
            payload["active_ids"][island][0] = "seed-unknown"
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    archive_path = root / "archive.jsonl"
    state_path = root / "state.json"
    before = (archive_path.read_bytes(), state_path.read_bytes(), target.read_bytes())

    with pytest.raises(EvolutionError, match=f"^{expected_error}$"):
        PopulationStrategy(
            EvolutionContext(
                contract,
                workspace,
                lambda request: pytest.fail("tampered resume generated offspring"),
                lambda path, supplied: pytest.fail("tampered resume evaluated a candidate"),
                config,
                initial_seeds=fresh_seeds,
            )
        ).resume()

    assert (archive_path.read_bytes(), state_path.read_bytes(), target.read_bytes()) == before


@pytest.mark.parametrize("changed", ["provenance", "dependency", "environment"])
def test_population_seeded_resume_rejects_changed_admission_authority(
    tmp_path: Path, changed: str
) -> None:
    contract = _contract()
    sources = {"candidate.py": "score = 1\n"}
    manifest = _seed_manifest(tmp_path / "incoming", contract, sources)
    seeds = _admitted_initial_seeds(manifest, contract, num_islands=1)
    workspace = tmp_path / "workspace"
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
    )
    PopulationStrategy(
        EvolutionContext(
            contract,
            workspace,
            lambda request: pytest.fail("cancelled seeded initialization generated offspring"),
            lambda path, supplied: pytest.fail("seed was evaluated again by the strategy"),
            config,
            cancelled=lambda: True,
            initial_seeds=seeds,
        )
    ).run()

    producer_run_id = "run-002" if changed == "provenance" else "run-001"
    dependency_sha256 = "e" * 64 if changed == "dependency" else SEED_DEPENDENCY_SHA
    environment_sha256 = "f" * 64 if changed == "environment" else SEED_ENVIRONMENT_SHA
    changed_manifest = _seed_manifest(
        tmp_path / "changed",
        contract,
        sources,
        producer_run_id=producer_run_id,
        dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
    )
    changed_seeds = _admitted_initial_seeds(
        changed_manifest,
        contract,
        num_islands=1,
        dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
    )
    if changed == "provenance":
        assert changed_seeds[0].candidate_id == seeds[0].candidate_id
    else:
        assert changed_seeds[0].candidate_id != seeds[0].candidate_id
    archive_path = workspace / "evolution" / "archive.jsonl"
    state_path = workspace / "evolution" / "state.json"
    before = (archive_path.read_bytes(), state_path.read_bytes())

    with pytest.raises(EvolutionError, match="^verified_seed_resume_mismatch$"):
        PopulationStrategy(
            EvolutionContext(
                contract,
                workspace,
                lambda request: pytest.fail("changed admission generated offspring"),
                lambda path, supplied: pytest.fail("changed admission evaluated a candidate"),
                config,
                initial_seeds=changed_seeds,
            )
        ).resume()

    assert (archive_path.read_bytes(), state_path.read_bytes()) == before


def test_retired_loop_strategy_remains_importable_but_cannot_mutate_state(
    tmp_path: Path,
) -> None:
    context = EvolutionContext(
        _contract("loop"),
        tmp_path,
        lambda request: CandidateDraft("unused"),
        lambda path, contract: _report(1),
        EvolutionConfig(),
    )

    with pytest.raises(EvolutionError, match="loop_strategy_retired"):
        LoopStrategy(context).run()
    with pytest.raises(EvolutionError, match="loop_strategy_retired"):
        LoopStrategy(context).resume()
    assert not (tmp_path / "evolution").exists()


def test_evolution_config_keeps_optional_adapter_fingerprints_credential_safe() -> None:
    legacy_payload = EvolutionConfig().to_dict()
    assert "generator_fingerprint" not in legacy_payload
    assert "evaluator_fingerprint" not in legacy_payload
    config = EvolutionConfig(
        generator_fingerprint="a" * 64,
        evaluator_fingerprint="b" * 64,
    )
    payload = config.to_dict()
    assert payload["generator_fingerprint"] == "a" * 64
    assert payload["evaluator_fingerprint"] == "b" * 64
    assert all("command" not in str(value) for value in payload.values())
    with pytest.raises(ValueError, match="SHA-256"):
        EvolutionConfig(generator_fingerprint="/absolute/path/to/solver --api-key secret")


def test_population_invalid_candidate_never_becomes_best(tmp_path: Path) -> None:
    def generate(request):
        return CandidateDraft(f"# {request.iteration}\n")

    def evaluate(path, contract):
        del path, contract
        return _report(10.0, valid=0)

    result = PopulationStrategy(
        EvolutionContext(_contract(), tmp_path, generate, evaluate, EvolutionConfig(max_rounds=2, stagnation_rounds=10, population_size=1))
    ).run()
    assert result.status == "failed"
    assert result.best_candidate_id is None
    assert result.best_candidate_path is None
    assert result.valid_candidates == 0


def test_command_candidate_runner_records_success_evidence(tmp_path: Path) -> None:
    runner_script = tmp_path / "runner.py"
    runner_script.write_text(
        "import pathlib, sys\n"
        "candidate = pathlib.Path(sys.argv[1])\n"
        "assert candidate.is_file()\n"
        "pathlib.Path('runner-output.txt').write_text('ok')\n"
        "pathlib.Path('execution-artifacts.json').write_text('[\"runner-output.txt\"]')\n"
        "print('candidate ran')\n",
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.py"
    candidate.write_text("print('candidate')\n", encoding="utf-8")
    runner = CommandCandidateRunner((sys.executable, str(runner_script)), max_output_bytes=128)

    execution = runner.run(candidate, tmp_path, timeout=2)

    assert isinstance(execution, CandidateExecution)
    assert execution.status == "succeeded"
    assert execution.exit_code == 0
    assert execution.stdout == "candidate ran"
    assert execution.artifacts == ("runner-output.txt",)
    evidence = json.loads((tmp_path / "execution.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "succeeded"
    assert evidence["stdout_bytes"] == len(b"candidate ran")


@pytest.mark.parametrize("mode", ["nonzero", "timeout", "output"])
def test_command_candidate_runner_fails_closed_with_bounded_evidence(
    tmp_path: Path, mode: str
) -> None:
    runner_script = tmp_path / "runner.py"
    behavior = {
        "nonzero": "print('failed'); raise SystemExit(3)",
        "timeout": "import time; time.sleep(2)",
        "output": "print('x' * 500)",
    }[mode]
    runner_script.write_text(f"import sys\n{behavior}\n", encoding="utf-8")
    candidate = tmp_path / "candidate.py"
    candidate.write_text("print('candidate')\n", encoding="utf-8")
    runner = CommandCandidateRunner(
        (sys.executable, str(runner_script)), max_output_bytes=64, timeout_seconds=1
    )

    execution = runner.run(candidate, tmp_path)

    assert execution.status in {"failed", "timed_out"}
    assert execution.error
    assert len(execution.stdout.encode()) <= 64
    assert len(execution.stderr.encode()) <= 64
    assert json.loads((tmp_path / "execution.json").read_text(encoding="utf-8"))["status"] == execution.status


def test_command_candidate_runner_rejects_candidate_escape(tmp_path: Path) -> None:
    runner_script = tmp_path / "runner.py"
    runner_script.write_text("import sys\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-candidate.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    runner = CommandCandidateRunner((sys.executable, str(runner_script)))

    with pytest.raises(EvolutionError, match="escapes"):
        runner.run(outside, tmp_path)


def test_execution_aware_evaluator_exposes_evidence_and_overrides_failed_runner(
    tmp_path: Path,
) -> None:
    contract = _contract()
    candidate = tmp_path / "candidate.py"
    candidate.write_text("print('candidate')\n", encoding="utf-8")
    runner_script = tmp_path / "runner.py"
    runner_script.write_text("print('ran')\n", encoding="utf-8")
    evaluator_script = tmp_path / "evaluator.py"
    evaluator_script.write_text(
        "import json, pathlib, sys\n"
        "candidate = pathlib.Path(sys.argv[1])\n"
        "evidence = json.loads((candidate.parent / 'execution.json').read_text())\n"
        "score = 4 if evidence['status'] == 'succeeded' else 99\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'fixture','validity':1,"
        "'quality':score,'combined_score':score,'detailed_scores':{},'error_info':[]}))\n",
        encoding="utf-8",
    )
    evaluator = CommandCandidateEvaluator((sys.executable, str(evaluator_script)))
    wrapped = ExecutionAwareCandidateEvaluator(
        CommandCandidateRunner((sys.executable, str(runner_script))), evaluator
    )

    report = wrapped(candidate, contract)

    assert report.validity == 1
    assert report.combined_score == 4
    assert (tmp_path / "execution.json").is_file()

    failing_script = tmp_path / "failing-runner.py"
    failing_script.write_text("raise SystemExit(2)\n", encoding="utf-8")
    failed = ExecutionAwareCandidateEvaluator(
        CommandCandidateRunner((sys.executable, str(failing_script))), evaluator
    )(candidate, contract)
    assert failed.validity == 0
    assert failed.combined_score == 0
    assert failed.error_info


def test_execution_aware_evaluator_propagates_evaluator_failure(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("pass\n", encoding="utf-8")

    class SuccessfulRunner:
        def run(self, candidate_path, workspace, timeout=None):
            del candidate_path, workspace, timeout
            return CandidateExecution(
                status="succeeded",
                exit_code=0,
                duration_ms=1,
            )

    def timeout_evaluator(path, contract):
        del path, contract
        raise TimeoutError("private evaluator detail")

    wrapped = ExecutionAwareCandidateEvaluator(SuccessfulRunner(), timeout_evaluator)
    with pytest.raises(TimeoutError, match="private evaluator detail"):
        wrapped(candidate, _contract())


def test_population_is_bounded_and_deterministic(tmp_path: Path) -> None:
    counter = {"value": 0}

    def generate(request):
        counter["value"] += 1
        return CandidateDraft(f"def solve_{counter['value']}():\n    return {counter['value']}\n")

    def evaluate(path, contract):
        del contract
        value = int(path.read_text().split("return ")[1].splitlines()[0])
        return _report(float(value))

    context = EvolutionContext(
        _contract("population"), tmp_path, generate, evaluate,
        EvolutionConfig(
            strategy="population", max_rounds=3, stagnation_rounds=10,
            population_size=4, offspring_per_iteration=2, num_islands=2,
            migration_interval=2, migration_rate=0.5, rng_seed=7,
        ),
    )
    result = PopulationStrategy(context).run()
    state = json.loads((tmp_path / "evolution" / "state.json").read_text())
    active = [item for ids in state["active_ids"].values() for item in ids]
    assert result.status == "completed"
    assert result.evaluated_candidates == 10  # four seeds plus six offspring
    assert len(active) <= 4
    assert len(active) == len(set(active))
    assert result.best_score == 10.0
    assert result.best_candidate_path is not None
    assert (tmp_path / result.best_candidate_path).is_file()


def test_result_does_not_handoff_missing_best_source(tmp_path: Path) -> None:
    def generate(request):
        return CandidateDraft("def solve():\n    return 1\n")

    result = PopulationStrategy(
        EvolutionContext(_contract(), tmp_path, generate, lambda path, contract: _report(1), EvolutionConfig(max_rounds=1, population_size=1))
    ).run()
    assert result.best_candidate_path is not None
    (tmp_path / result.best_candidate_path).unlink()
    recovered = CandidateArchive(tmp_path).result("population", "completed", 1)
    assert recovered.best_candidate_id is None
    assert recovered.best_candidate_path is None


def _write_fake_openevolve(
    root: Path,
    *,
    producer_counter: Path | None = None,
    stderr: str | None = None,
    exit_code: int = 0,
) -> Path:
    fake = root / "fake_openevolve.py"
    lines = ["import json, pathlib, sys"]
    if producer_counter is not None:
        lines.extend(
            [
                f"counter = pathlib.Path({str(producer_counter)!r})",
                "count = int(counter.read_text()) if counter.exists() else 0",
                "counter.write_text(str(count + 1))",
            ]
        )
    if stderr is not None:
        lines.append(f"sys.stderr.write({stderr!r})")
    if exit_code:
        lines.append(f"raise SystemExit({exit_code})")
    else:
        lines.extend(
            [
                "cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())",
                "assert cfg['schema_version'] == '1'",
                "assert cfg['producer']['id'] == 'openevolve'",
                "root = pathlib.Path.cwd()",
                "(root / 'candidate.py').write_text('def solve():\\n    return 42\\n')",
                (
                    "evaluation = {'schema_version':'1','evaluator_id':'remote-private-label',"
                    "'validity':1,'quality':987654321.125,'combined_score':987654321.125,"
                    "'detailed_scores':{},'error_info':[],"
                    "'note':'remote producer prose must not persist'}"
                ),
                (
                    "(root / 'result.json').write_text(json.dumps("
                    "{'candidate_path':'candidate.py','evaluation':evaluation}))"
                ),
            ]
        )
    fake.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fake


def _openevolve_config(command: tuple[str, ...], **overrides: object) -> EvolutionConfig:
    values: dict[str, object] = {
        "strategy": "openevolve",
        "command": command,
        "timeout_seconds": 5,
        "evaluator_fingerprint": SEED_EVALUATOR_SHA,
    }
    values.update(overrides)
    return EvolutionConfig(**values)  # type: ignore[arg-type]


def test_strategy_selector_accepts_openevolve_only_with_explicit_command_and_evaluator(
    tmp_path: Path,
) -> None:
    contract = _contract("openevolve")
    config = _openevolve_config((sys.executable, "-c", "pass"))
    context = EvolutionContext(contract, tmp_path, lambda request: CandidateDraft("x"), lambda p, c: _report(1), config)
    assert isinstance(build_strategy(context), OpenEvolveStrategy)
    try:
        EvolutionConfig(strategy="openevolve", evaluator_fingerprint=SEED_EVALUATOR_SHA)
    except ValueError as exc:
        assert "explicit command" in str(exc)
    else:
        raise AssertionError("missing OpenEvolve command must fail")

    with pytest.raises(ValueError, match="pinned local evaluator fingerprint"):
        EvolutionConfig(strategy="openevolve", command=(sys.executable, "-c", "pass"))


def test_openevolve_adapter_commits_verified_seed_evidence_without_external_payload(
    tmp_path: Path,
) -> None:
    fake = _write_fake_openevolve(tmp_path)

    def evaluate(path, contract):
        del contract
        assert path.is_file()
        return _report(0.75)

    context = EvolutionContext(
        _contract("openevolve"), tmp_path, lambda request: CandidateDraft("unused"), evaluate,
        _openevolve_config((sys.executable, str(fake))),
    )
    strategy = OpenEvolveStrategy(context)
    producer_fingerprint = strategy._producer_fingerprint()
    result = strategy.run()
    source = b"def solve():\n    return 42\n"
    source_sha256 = hashlib.sha256(source).hexdigest()
    dependency_sha256 = source_only_dependency_sha256(source_sha256)
    environment_sha256 = declared_protocol_environment_sha256()
    identity_payload = {
        "schema_version": "1",
        "source_sha256": source_sha256,
        "contract_sha256": context.contract.digest(),
        "evaluator_kind": "exact_harness",
        "evaluator_fingerprint": SEED_EVALUATOR_SHA,
        "dependency_sha256": dependency_sha256,
        "environment_sha256": environment_sha256,
        "lineage": [],
    }
    expected_id = f"seed-{evolution_module._canonical_seed_sha256(identity_payload)}"

    assert result.status == "completed"
    assert result.best_score == 0.75
    assert result.best_candidate_id == expected_id
    assert result.best_candidate_path == f"evolution/candidates/{expected_id}/candidate.py"
    candidate_root = tmp_path / "evolution" / "candidates" / expected_id
    assert (candidate_root / "candidate.py").read_bytes() == source

    record = CandidateArchive(tmp_path).records()[0]
    assert record.candidate_id == expected_id
    assert record.strategy == "openevolve"
    assert record.iteration == 1
    assert record.generation == 0
    assert record.parent_id is None
    assert record.island_id is None
    assert record.evaluation.evaluator_id == "fixture"
    assert record.evaluation.combined_score == 0.75

    receipt = json.loads((candidate_root / "receipt.json").read_text(encoding="utf-8"))
    receipt_payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert set(receipt) == evolution_module._SEED_RECEIPT_FIELDS
    assert receipt["candidate_id"] == expected_id
    assert receipt["evaluator_kind"] == "exact_harness"
    assert receipt["evaluator_fingerprint"] == SEED_EVALUATOR_SHA
    assert receipt["combined_score"] == 0.75
    assert receipt["error_info"] == []
    assert receipt["receipt_sha256"] == evolution_module._canonical_seed_sha256(receipt_payload)

    persisted_record = json.loads((candidate_root / "record.json").read_text(encoding="utf-8"))
    evidence = persisted_record["seed_handoff_evidence"]
    assert set(evidence) == {
        "schema_version",
        "provenance",
        "external_evidence",
        "provenance_sha256",
        "handoff_sha256",
        "receipt_sha256",
    }
    assert evidence["provenance"] == record.metadata["seed_handoff"]["provenance"]
    assert evidence["external_evidence"]["present"] is True
    assert evidence["external_evidence"]["score_present"] is True
    assert len(evidence["external_evidence"]["payload_sha256"]) == 64
    assert evidence["receipt_sha256"] == receipt["receipt_sha256"]
    expected_projection = {
        "origin_kind": "external",
        "producer_id": "openevolve",
        "producer_fingerprint": producer_fingerprint,
        "producer_run_id": None,
        "material_refs_sha256": evolution_module._canonical_seed_sha256([]),
        "external_evidence_sha256": evolution_module._canonical_seed_sha256(
            evidence["external_evidence"]
        ),
    }
    assert evidence["provenance"] == expected_projection
    assert record.metadata["seed_handoff"]["provenance"] == expected_projection
    expected_provenance = {
        "origin_kind": "external",
        "producer_id": "openevolve",
        "producer_fingerprint": producer_fingerprint,
        "producer_run_id": None,
        "material_refs": [],
        "external_evidence": evidence["external_evidence"],
    }
    assert evidence["provenance_sha256"] == evolution_module._canonical_seed_sha256(
        expected_provenance
    )
    assert evidence["handoff_sha256"] == evolution_module._canonical_seed_sha256(
        {
            "schema_version": "1",
            "candidate_id": expected_id,
            "provenance": expected_provenance,
        }
    )
    assert set(record.metadata["seed_metadata"]) == {
        "present",
        "score_present",
        "payload_sha256",
    }
    assert record.metadata["seed_metadata"]["present"] is True
    assert record.metadata["seed_metadata"]["score_present"] is False
    assert len(record.metadata["seed_metadata"]["payload_sha256"]) == 64

    state = json.loads((tmp_path / "evolution" / "state.json").read_text(encoding="utf-8"))
    assert set(state) == {
        "schema_version",
        "strategy",
        "status",
        "iteration",
        "contract_sha256",
        "config",
        "error",
        "best_candidate_id",
        "seed_admission",
    }
    assert state["strategy"] == "openevolve"
    assert state["status"] == "completed"
    assert state["iteration"] == 1
    assert state["best_candidate_id"] == expected_id
    summary = state["seed_admission"]
    assert summary["seeds"] == [
        {
            "candidate_id": expected_id,
            "receipt_sha256": receipt["receipt_sha256"],
            "handoff_sha256": evidence["handoff_sha256"],
            "provenance_sha256": evidence["provenance_sha256"],
        }
    ]
    assert summary["admission_sha256"] == evolution_module._canonical_seed_sha256(
        {"schema_version": "1", "seeds": summary["seeds"]}
    )

    marker = json.loads(
        (tmp_path / "evolution" / "seed-commit.json").read_text(encoding="utf-8")
    )
    marker_payload = {key: value for key, value in marker.items() if key != "commit_sha256"}
    assert set(marker) == {
        "schema_version",
        "admission_sha256",
        "candidate_ids",
        "seed_candidates_sha256",
        "commit_sha256",
    }
    assert marker["candidate_ids"] == [expected_id]
    assert marker["admission_sha256"] == summary["admission_sha256"]
    assert marker["seed_candidates_sha256"] == evolution_module._canonical_seed_sha256(
        [record.to_dict()]
    )
    assert marker["commit_sha256"] == evolution_module._canonical_seed_sha256(marker_payload)

    persisted = b"".join(
        path.read_bytes() for path in (tmp_path / "evolution").rglob("*") if path.is_file()
    )
    assert b"987654321.125" not in persisted
    assert b"remote-private-label" not in persisted
    assert b"remote producer prose must not persist" not in persisted


def test_openevolve_resume_runs_producer_once_and_local_evaluator_twice(tmp_path: Path) -> None:
    producer_counter = tmp_path / "producer-count.txt"
    fake = _write_fake_openevolve(tmp_path, producer_counter=producer_counter)
    evaluations = 0

    def evaluate(path, contract):
        nonlocal evaluations
        del path, contract
        evaluations += 1
        return _report(0.75)

    config = _openevolve_config((sys.executable, str(fake)))
    context = EvolutionContext(
        _contract("openevolve"),
        tmp_path,
        lambda request: pytest.fail("OpenEvolve must not call the Lunar generator"),
        evaluate,
        config,
    )

    first = OpenEvolveStrategy(context).run()
    evolution_root = tmp_path / "evolution"
    persisted_before = {
        path.relative_to(evolution_root): path.read_bytes()
        for path in evolution_root.rglob("*")
        if path.is_file()
    }
    fake.unlink()
    second = OpenEvolveStrategy(context).resume()

    assert first.status == second.status == "completed"
    assert first.best_candidate_id == second.best_candidate_id
    assert producer_counter.read_text(encoding="utf-8") == "1"
    assert evaluations == 2
    assert {
        path.relative_to(evolution_root): path.read_bytes()
        for path in evolution_root.rglob("*")
        if path.is_file()
    } == persisted_before


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("source", "openevolve_resume_mismatch"),
        ("receipt", "openevolve_resume_mismatch"),
        ("config", "evolution state configuration does not match the supplied configuration"),
    ],
)
def test_openevolve_resume_rejects_tampered_canonical_material(
    tmp_path: Path,
    target: str,
    expected: str,
) -> None:
    producer_counter = tmp_path / "producer-count.txt"
    fake = _write_fake_openevolve(tmp_path, producer_counter=producer_counter)
    config = _openevolve_config((sys.executable, str(fake)))
    context = EvolutionContext(
        _contract("openevolve"),
        tmp_path,
        lambda request: pytest.fail("OpenEvolve must not call the Lunar generator"),
        lambda path, contract: _report(0.75),
        config,
    )
    completed = OpenEvolveStrategy(context).run()
    assert completed.best_candidate_id is not None
    candidate_root = tmp_path / "evolution" / "candidates" / completed.best_candidate_id
    if target == "source":
        (candidate_root / "candidate.py").write_text("tampered = True\n", encoding="utf-8")
    elif target == "receipt":
        receipt_path = candidate_root / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["combined_score"] = 1000
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    else:
        state_path = tmp_path / "evolution" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["config"]["timeout_seconds"] = 6
        state_path.write_text(json.dumps(state), encoding="utf-8")

    evolution_root = tmp_path / "evolution"
    persisted_after_tamper = {
        path.relative_to(evolution_root): path.read_bytes()
        for path in evolution_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(EvolutionError, match=f"^{expected}$"):
        OpenEvolveStrategy(context).resume()

    assert producer_counter.read_text(encoding="utf-8") == "1"
    assert {
        path.relative_to(evolution_root): path.read_bytes()
        for path in evolution_root.rglob("*")
        if path.is_file()
    } == persisted_after_tamper
    assert len((evolution_root / "archive.jsonl").read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("outcome", ["exception", "invalid", "none"])
def test_openevolve_local_evaluator_failure_commits_no_candidate(
    tmp_path: Path,
    outcome: str,
) -> None:
    fake = _write_fake_openevolve(tmp_path)

    def evaluate(path, contract):
        del path, contract
        if outcome == "exception":
            raise RuntimeError("private evaluator exception prose")
        if outcome == "invalid":
            return _report(1, valid=0)
        return None

    context = EvolutionContext(
        _contract("openevolve"),
        tmp_path,
        lambda request: pytest.fail("OpenEvolve must not call the Lunar generator"),
        evaluate,
        _openevolve_config((sys.executable, str(fake))),
    )
    result = OpenEvolveStrategy(context).run()

    assert result.status == "failed"
    assert result.error == "openevolve_local_evaluation_failed"
    assert result.evaluated_candidates == result.valid_candidates == 0
    assert result.best_candidate_id is None
    assert not (tmp_path / "evolution" / "archive.jsonl").exists()
    assert list((tmp_path / "evolution" / "candidates").iterdir()) == []
    state = (tmp_path / "evolution" / "state.json").read_text(encoding="utf-8")
    assert "private evaluator exception prose" not in state
    assert "fixture candidate is invalid" not in state


def test_openevolve_stderr_credentials_are_not_persisted(tmp_path: Path) -> None:
    secret = "sk-openevolve-secret-123456789"
    fake = _write_fake_openevolve(tmp_path, stderr=secret, exit_code=9)
    context = EvolutionContext(
        _contract("openevolve"),
        tmp_path,
        lambda request: pytest.fail("OpenEvolve must not call the Lunar generator"),
        lambda path, contract: pytest.fail("failed producer must not call the evaluator"),
        _openevolve_config((sys.executable, str(fake))),
    )

    result = OpenEvolveStrategy(context).run()

    assert result.status == "failed"
    assert result.error == "openevolve_command_failed"
    assert result.evaluated_candidates == 0
    persisted = b"".join(
        path.read_bytes() for path in (tmp_path / "evolution").rglob("*") if path.is_file()
    )
    assert secret.encode("utf-8") not in persisted


def test_openevolve_rejects_relative_executable_without_writing_candidate(tmp_path: Path) -> None:
    context = EvolutionContext(
        _contract("openevolve"), tmp_path, lambda request: CandidateDraft("unused"), lambda p, c: _report(1),
        _openevolve_config(("python", "fake.py")),
    )
    result = OpenEvolveStrategy(context).run()
    assert result.status == "failed"
    assert result.error == "openevolve_command_invalid"
    assert result.evaluated_candidates == 0
    assert not (tmp_path / "evolution" / "archive.jsonl").exists()
