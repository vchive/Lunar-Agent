"""Offline controller checks for ordinary candidate evidence indexing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionError,
)
from famou.runtime import MockRuntime

SEED_EVALUATOR_SHA = "a" * 64
SEED_DEPENDENCY_SHA = "b" * 64
SEED_ENVIRONMENT_SHA = "c" * 64
SEED_PRODUCER_SHA = "d" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "controller-integrity-fixture",
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every item is served."],
            "deliverables": ["route source"],
            "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 4},
        }
    )


def _report() -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "controller-fixture",
            "validity": 1,
            "quality": 0.5,
            "combined_score": 0.5,
            "detailed_scores": {},
            "error_info": [],
        }
    )


def _seed_manifest(root: Path, contract: AlgorithmProblemContract) -> Path:
    root.mkdir(parents=True)
    source = root / "seed.py"
    source.write_text("seed = 1\n", encoding="utf-8")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "contract_sha256": contract.digest(),
                "evaluator": {
                    "kind": "exact_harness",
                    "fingerprint": SEED_EVALUATOR_SHA,
                },
                "dependency_sha256": SEED_DEPENDENCY_SHA,
                "environment_sha256": SEED_ENVIRONMENT_SHA,
                "seeds": [
                    {
                        "source_path": source.name,
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "lineage": [],
                        "provenance": {
                            "origin_kind": "external",
                            "producer_id": "openevolve",
                            "producer_fingerprint": SEED_PRODUCER_SHA,
                            "producer_run_id": "run-seed-fixture",
                            "material_refs": [],
                            "external_evidence": {"external_score": 1.0},
                        },
                        "metadata": {},
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def test_controller_indexes_ordinary_record_and_receipt_idempotently(tmp_path: Path) -> None:
    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )
    seed_orphan = Path(run.workspace) / "evolution" / "candidates" / "seed-orphan"
    seed_orphan.mkdir(parents=True)
    for name in ("record.json", "receipt.json"):
        (seed_orphan / name).write_text('{"orphan":true}\n', encoding="utf-8")

    settled, result = controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
        lambda path, supplied: _report(),
        config,
    )
    assert settled.status.value == "succeeded"
    assert result.best_candidate_id == "candidate-0001"

    rows = controller.store.list_artifacts(run.id)
    ordinary = [
        item
        for item in rows
        if item["kind"] in {"evolution_candidate_record", "evolution_candidate_receipt"}
    ]
    assert {item["kind"] for item in ordinary} == {
        "evolution_candidate_record",
        "evolution_candidate_receipt",
    }
    assert len(ordinary) == 4
    assert not any("seed-orphan" in item["path"] for item in rows)
    assert {
        item["path"].split("/")[2]
        for item in ordinary
    } == {"candidate-0001", "candidate-0002"}

    # A terminal resume re-runs the indexing hook.  The ledger must retain one row per stable
    # path/kind pair even though Store artifact IDs are random UUIDs.
    controller.run_evolution(run.id, contract, lambda request: None, lambda path, supplied: None, config)
    repeated = [
        item
        for item in controller.store.list_artifacts(run.id)
        if item["kind"] in {"evolution_candidate_record", "evolution_candidate_receipt"}
    ]
    assert len(repeated) == 4
    assert {(item["path"], item["kind"]) for item in repeated} == {
        ("evolution/candidates/candidate-0001/record.json", "evolution_candidate_record"),
        ("evolution/candidates/candidate-0001/receipt.json", "evolution_candidate_receipt"),
        ("evolution/candidates/candidate-0002/record.json", "evolution_candidate_record"),
        ("evolution/candidates/candidate-0002/receipt.json", "evolution_candidate_receipt"),
    }


def test_controller_indexes_nested_ordinary_sidecars_from_archive_code_path(tmp_path: Path) -> None:
    """Sidecars follow the source parent, including a nested candidate filename."""

    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )
    controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft("answer = 1\n", filename="src/main.py"),
        lambda path, supplied: _report(),
        config,
    )
    rows = controller.store.list_artifacts(run.id)
    paths = {
        (item["path"], item["kind"])
        for item in rows
        if item["kind"].startswith("evolution_candidate_")
    }
    assert paths == {
        (f"evolution/candidates/candidate-{index:04d}/src/{name}.json", kind)
        for index in (1, 2)
        for name, kind in (
            ("record", "evolution_candidate_record"),
            ("receipt", "evolution_candidate_receipt"),
        )
    }
    # Confirm the archive remains the source of visibility; an unrelated sidecar is ignored.
    orphan = Path(run.workspace) / "evolution" / "candidates" / "orphan" / "record.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(json.dumps({"orphan": True}), encoding="utf-8")
    archive = CandidateArchive(run.workspace)
    controller._index_evolution_candidate_integrity_artifacts(run, controller.store.list_tasks(run.id)[0].id)
    assert not any(item["path"].endswith("orphan/record.json") for item in controller.store.list_artifacts(run.id))
    assert archive.records()


def test_controller_observes_each_ordinary_candidate_once(tmp_path: Path) -> None:
    """Candidate persistence emits one controller archive event per durable record."""

    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )

    controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
        lambda path, supplied: _report(),
        config,
    )

    archived_ids = [
        event["payload"]["candidate_id"]
        for event in controller.store.list_events(run.id)
        if event["type"] == "evolution_candidate_archived"
    ]
    record_ids = [candidate.candidate_id for candidate in CandidateArchive(run.workspace).records()]
    assert archived_ids == record_ids == ["candidate-0001", "candidate-0002"]


def test_controller_indexes_published_sidecars_after_state_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )
    original_write_state = CandidateArchive.write_state
    state_write_failed = False

    def fail_after_candidate_publication(self, payload):
        nonlocal state_write_failed
        if (
            not state_write_failed
            and payload.get("status") == "running"
            and payload.get("iteration") == 0
            and self.records()
        ):
            state_write_failed = True
            raise OSError("simulated state write failure")
        original_write_state(self, payload)

    monkeypatch.setattr(CandidateArchive, "write_state", fail_after_candidate_publication)
    with pytest.raises(EvolutionError, match="simulated state write failure"):
        controller.run_evolution(
            run.id,
            contract,
            lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
            lambda path, supplied: _report(),
            config,
        )

    assert state_write_failed
    archive = CandidateArchive(run.workspace)
    assert [candidate.candidate_id for candidate in archive.records()] == [
        "candidate-0001"
    ]
    indexed = {
        (item["path"], item["kind"]): item
        for item in controller.store.list_artifacts(run.id)
        if item["kind"] in {
            "evolution_candidate_record",
            "evolution_candidate_receipt",
        }
    }
    expected = {
        (
            "evolution/candidates/candidate-0001/record.json",
            "evolution_candidate_record",
        ),
        (
            "evolution/candidates/candidate-0001/receipt.json",
            "evolution_candidate_receipt",
        ),
    }
    assert set(indexed) == expected
    for relative, kind in expected:
        content = (Path(run.workspace) / relative).read_bytes()
        assert indexed[(relative, kind)]["size"] == len(content)
        assert indexed[(relative, kind)]["sha256"] == hashlib.sha256(content).hexdigest()
    assert controller.store.get_run(run.id).status.value == "failed"


@pytest.mark.parametrize(
    ("offspring_count", "fail_on_append", "expected_archive_ids"),
    [
        (1, 1, ["candidate-0001", "candidate-0002"]),
        (2, 2, ["candidate-0001", "candidate-0002", "candidate-0003"]),
    ],
)
def test_controller_indexes_state_bound_prefix_after_outcome_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offspring_count: int,
    fail_on_append: int,
    expected_archive_ids: list[str],
) -> None:
    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=offspring_count,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )

    original_append = CandidateArchive.append_offspring_outcome
    append_calls = 0

    def fail_outcome_append(self, outcome):
        nonlocal append_calls
        append_calls += 1
        if append_calls == fail_on_append:
            raise OSError("simulated outcome append failure")
        original_append(self, outcome)

    monkeypatch.setattr(
        CandidateArchive,
        "append_offspring_outcome",
        fail_outcome_append,
    )
    with pytest.raises(EvolutionError, match="simulated outcome append failure"):
        controller.run_evolution(
            run.id,
            contract,
            lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
            lambda path, supplied: _report(),
            config,
        )

    archive = CandidateArchive(run.workspace)
    assert [candidate.candidate_id for candidate in archive.records()] == expected_archive_ids
    assert len(archive.offspring_outcomes()) == fail_on_append - 1
    indexed = {
        (item["path"], item["kind"])
        for item in controller.store.list_artifacts(run.id)
        if item["kind"] in {
            "evolution_candidate_record",
            "evolution_candidate_receipt",
        }
    }
    assert indexed == {
        (
            "evolution/candidates/candidate-0001/record.json",
            "evolution_candidate_record",
        ),
        (
            "evolution/candidates/candidate-0001/receipt.json",
            "evolution_candidate_receipt",
        ),
    }


def test_controller_failure_does_not_index_uncommitted_seed_sidecars(
    tmp_path: Path,
) -> None:
    """Archive metadata alone cannot publish verified-seed evidence to the ledger."""

    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )
    workspace = Path(run.workspace)
    candidate_root = workspace / "evolution" / "candidates" / "seed-forged"
    candidate_root.mkdir(parents=True)
    source = candidate_root / "candidate.py"
    source.write_text("forged = True\n", encoding="utf-8")
    forged = Candidate(
        candidate_id="seed-forged",
        code_path=source.relative_to(workspace).as_posix(),
        parent_id=None,
        generation=0,
        iteration=0,
        strategy="population",
        island_id=0,
        evaluation=_report(),
        metadata={"seed_handoff": {"uncommitted": True}},
    )
    archive = CandidateArchive(workspace)
    archive.root.mkdir(parents=True, exist_ok=True)
    archive.archive_path.write_text(
        json.dumps(forged.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name in ("record.json", "receipt.json"):
        (candidate_root / name).write_text(
            json.dumps({"attacker_controlled": name}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(
        EvolutionError,
        match="^verified_seed_resume_requires_initial_seeds$",
    ):
        controller.run_evolution(
            run.id,
            contract,
            lambda request: pytest.fail("uncommitted seed generated"),
            lambda path, supplied: pytest.fail("uncommitted seed evaluated"),
            config,
        )

    assert not (workspace / "evolution" / "state.json").exists()
    assert not (workspace / "evolution" / "seed-commit.json").exists()
    assert not any(
        item["kind"] in {"evolution_seed_record", "evolution_seed_receipt"}
        for item in controller.store.list_artifacts(run.id)
    )

    # The generic maintenance hook also delegates population seed evidence exclusively to the
    # state/commit-marker-bound admission recorder.
    controller._index_evolution_candidate_integrity_artifacts(
        run,
        controller.store.list_tasks(run.id)[0].id,
    )
    assert not any(
        item["kind"] in {"evolution_seed_record", "evolution_seed_receipt"}
        for item in controller.store.list_artifacts(run.id)
    )


def test_controller_rejects_conflicting_duplicate_candidate_artifact_rows(
    tmp_path: Path,
) -> None:
    contract = _contract()
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        evaluator_kind="callback",
        evaluator_fingerprint="a" * 64,
        generator_fingerprint="b" * 64,
        runner_fingerprint="c" * 64,
        dependency_sha256="d" * 64,
        environment_sha256="e" * 64,
    )
    controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft("candidate = 1\n"),
        lambda path, supplied: _report(),
        config,
    )

    row = next(
        item
        for item in controller.store.list_artifacts(run.id)
        if item["kind"] == "evolution_candidate_record"
    )
    task_id = controller.store.list_tasks(run.id)[0].id
    controller.store.add_artifact(
        run.id,
        task_id,
        row["path"],
        "0" * 64,
        row["size"] + 1,
        row["kind"],
    )

    with pytest.raises(
        EvolutionError,
        match="^evolution candidate artifact digest mismatch$",
    ):
        controller._index_evolution_candidate_integrity_artifacts(
            run,
            task_id,
        )


@pytest.mark.parametrize("resume_mode", ["terminal", "active"])
@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    [
        ("source", "ordinary_candidate_source_mismatch"),
        ("receipt", "ordinary_candidate_receipt_invalid"),
    ],
)
def test_seeded_controller_preflights_ordinary_integrity_before_seed_evaluation(
    tmp_path: Path,
    resume_mode: str,
    tamper: str,
    expected_error: str,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(tmp_path / "incoming", contract)
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=1,
        evaluator_kind="exact_harness",
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
        generator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256=SEED_DEPENDENCY_SHA,
        environment_sha256=SEED_ENVIRONMENT_SHA,
    )

    settled, _ = controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft(
            f"ordinary = {request.iteration}\n",
            filename="src/main.py",
        ),
        lambda path, supplied: _report(),
        config,
        seed_manifest=manifest,
        seed_dependency_sha256=SEED_DEPENDENCY_SHA,
        seed_environment_sha256=SEED_ENVIRONMENT_SHA,
    )
    assert settled.status.value == "succeeded"
    records = CandidateArchive(run.workspace).records()
    ordinary = [candidate for candidate in records if not candidate.candidate_id.startswith("seed-")]
    assert len(ordinary) == 1
    source = Path(run.workspace) / ordinary[0].code_path
    if tamper == "source":
        source.write_text("ordinary = tampered\n", encoding="utf-8")
    else:
        receipt_path = source.parent / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["combined_score"] = 0.75
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")

    if resume_mode == "active":
        with controller.store._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = 'running' WHERE id = ?",
                (run.id,),
            )
            connection.execute(
                "UPDATE tasks SET state = 'running' WHERE run_id = ?",
                (run.id,),
            )

    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("ordinary-integrity preflight generated")

    def must_not_evaluate(path, supplied):
        del path, supplied
        callbacks["evaluate"] += 1
        pytest.fail("ordinary-integrity preflight invoked the seed evaluator")

    with pytest.raises(EvolutionError, match=f"^{expected_error}$"):
        controller.run_evolution(
            run.id,
            contract,
            must_not_generate,
            must_not_evaluate,
            config,
            resume=resume_mode == "active",
            seed_manifest=manifest,
            seed_dependency_sha256=SEED_DEPENDENCY_SHA,
            seed_environment_sha256=SEED_ENVIRONMENT_SHA,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    [
        ("incomplete_pending", "population_iteration_incomplete"),
        ("unknown_active", "population state references an unknown candidate"),
        ("empty_active", "verified_seed_active_population_missing"),
    ],
)
def test_seeded_controller_preflights_ordinary_state_before_seed_evaluation(
    tmp_path: Path,
    tamper: str,
    expected_error: str,
) -> None:
    contract = _contract()
    manifest = _seed_manifest(tmp_path / "incoming", contract)
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = EvolutionConfig(
        max_rounds=1,
        population_size=1,
        offspring_per_iteration=1,
        evaluator_kind="exact_harness",
        evaluator_fingerprint=SEED_EVALUATOR_SHA,
        generator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256=SEED_DEPENDENCY_SHA,
        environment_sha256=SEED_ENVIRONMENT_SHA,
    )

    settled, _ = controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft(f"ordinary = {request.iteration}\n"),
        lambda path, supplied: _report(),
        config,
        seed_manifest=manifest,
        seed_dependency_sha256=SEED_DEPENDENCY_SHA,
        seed_environment_sha256=SEED_ENVIRONMENT_SHA,
    )
    assert settled.status.value == "succeeded"
    records = CandidateArchive(run.workspace).records()
    assert any(candidate.candidate_id.startswith("seed-") for candidate in records)
    assert any(not candidate.candidate_id.startswith("seed-") for candidate in records)

    state_path = Path(run.workspace) / "evolution" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "running"
    if tamper == "incomplete_pending":
        state["pending_offspring"] = {
            "schema_version": "1",
            "iteration": 2,
            "attempt_count": 1,
        }
    elif tamper == "unknown_active":
        state["active_ids"] = {"0": ["candidate-unknown"]}
    else:
        state["active_ids"] = {"0": []}
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with controller.store._connect() as connection:
        connection.execute(
            "UPDATE runs SET status = 'running' WHERE id = ?",
            (run.id,),
        )
        connection.execute(
            "UPDATE tasks SET state = 'running' WHERE run_id = ?",
            (run.id,),
        )

    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("ordinary-state preflight generated")

    def must_not_evaluate(path, supplied):
        del path, supplied
        callbacks["evaluate"] += 1
        pytest.fail("ordinary-state preflight invoked the seed evaluator")

    with pytest.raises(EvolutionError, match=f"^{expected_error}$"):
        controller.run_evolution(
            run.id,
            contract,
            must_not_generate,
            must_not_evaluate,
            config,
            resume=True,
            seed_manifest=manifest,
            seed_dependency_sha256=SEED_DEPENDENCY_SHA,
            seed_environment_sha256=SEED_ENVIRONMENT_SHA,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}
