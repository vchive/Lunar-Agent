"""Offline regression tests for ordinary population candidate integrity (Feature 087).

These fixtures deliberately use callback generator/evaluator boundaries.  They do not start a
model, external evolution producer, remote transport, scheduler, or benchmark campaign.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

import famou
import famou.evolution as evolution_module
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import (
    LEGACY_CANDIDATE_INTEGRITY_ERROR,
    MAX_ARCHIVE_LINE_BYTES,
    MAX_SOURCE_BYTES,
    CandidateArchive,
    CandidateDraft,
    CandidateExecution,
    CandidateIntegrityAuthority,
    CandidateReceipt,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    OffspringOutcome,
    PopulationStrategy,
    WorkerUnknownError,
)
from famou.runtime import MockRuntime

GENERATOR_SHA = "1" * 64
EVALUATOR_SHA = "2" * 64
RUNNER_SHA = "3" * 64
DEPENDENCY_SHA = "4" * 64
ENVIRONMENT_SHA = "5" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "ordinary-integrity-fixture",
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
            "evolution": {"strategy": "population", "max_rounds": 2, "stagnation_rounds": 5},
        }
    )


def _report(score: float, *, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "integrity-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
            "error_info": []
            if valid
            else [{"code": "invalid", "message": "fixture candidate is invalid"}],
        }
    )


def _config(**overrides: object) -> EvolutionConfig:
    values: dict[str, object] = {
        "max_rounds": 1,
        "stagnation_rounds": 10,
        "population_size": 1,
        "offspring_per_iteration": 1,
        "generator_fingerprint": GENERATOR_SHA,
        "evaluator_kind": "callback",
        "evaluator_fingerprint": EVALUATOR_SHA,
        "dependency_sha256": DEPENDENCY_SHA,
        "environment_sha256": ENVIRONMENT_SHA,
        "runner_fingerprint": RUNNER_SHA,
    }
    values.update(overrides)
    return EvolutionConfig(**values)  # type: ignore[arg-type]


def _run(
    workspace: Path,
    *,
    config: EvolutionConfig | None = None,
    generate=None,
    evaluate=None,
):
    contract = _contract()
    generate = generate or (lambda request: CandidateDraft(f"iteration = {request.iteration}\n"))
    evaluate = evaluate or (lambda path, supplied: _report(0.5))
    context = EvolutionContext(
        contract,
        workspace,
        generate,
        evaluate,
        config or _config(),
    )
    return PopulationStrategy(context).run()


def _resume(
    workspace: Path,
    *,
    config: EvolutionConfig | None = None,
    generate=None,
    evaluate=None,
):
    contract = _contract()
    generate = generate or (lambda request: CandidateDraft(f"iteration = {request.iteration}\n"))
    evaluate = evaluate or (lambda path, supplied: _report(0.5))
    context = EvolutionContext(
        contract,
        workspace,
        generate,
        evaluate,
        config or _config(),
    )
    return PopulationStrategy(context).resume()


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_files(workspace: Path, candidate_id: str) -> tuple[Path, Path, Path]:
    root = workspace / "evolution" / "candidates" / candidate_id
    return root / "candidate.py", root / "record.json", root / "receipt.json"


def _authority() -> CandidateIntegrityAuthority:
    return CandidateIntegrityAuthority(
        schema_version="1",
        contract_sha256=_contract().digest(),
        evaluator_kind="callback",
        evaluator_fingerprint=EVALUATOR_SHA,
        dependency_sha256=DEPENDENCY_SHA,
        environment_sha256=ENVIRONMENT_SHA,
        runner_fingerprint=RUNNER_SHA,
        generator_fingerprint=GENERATOR_SHA,
    )


def test_ordinary_integrity_public_api_exports_are_consistent() -> None:
    names = {
        "CandidateIntegrityAuthority",
        "CandidateReceipt",
        "resolve_candidate_integrity_authority",
    }
    assert names <= set(evolution_module.__all__)
    assert all(hasattr(famou, name) for name in names)


def test_population_persists_canonical_receipts_and_lineage_projection(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)
    assert result.status == "completed"

    archive = CandidateArchive(tmp_path)
    records = archive.records()
    assert [item.candidate_id for item in records] == ["candidate-0001", "candidate-0002"]
    assert records[0].parent_id is None
    assert records[0].generation == 0
    assert records[0].iteration == 0
    assert records[1].parent_id == records[0].candidate_id
    assert records[1].generation == 1
    assert records[1].iteration == 1

    archive_lines = [json.loads(line) for line in archive.archive_path.read_text().splitlines()]
    assert len(archive_lines) == len(records)
    for candidate, line in zip(records, archive_lines, strict=True):
        source_path, record_path, receipt_path = _candidate_files(tmp_path, candidate.candidate_id)
        assert source_path.is_file()
        assert record_path.is_file()
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text())
        assert set(receipt) == {
            "schema_version",
            "candidate_id",
            "source_sha256",
            "contract_sha256",
            "evaluator_kind",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "runner_fingerprint",
            "generator_fingerprint",
            "parent_id",
            "generation",
            "iteration",
            "island_id",
            "report_schema_version",
            "evaluator_id",
            "validity",
            "quality",
            "combined_score",
            "detailed_scores",
            "error_info",
            "execution_sha256",
            "receipt_sha256",
        }
        assert receipt["candidate_id"] == candidate.candidate_id
        assert receipt["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
        assert receipt["contract_sha256"] == _contract().digest()
        assert receipt["evaluator_kind"] == "callback"
        assert receipt["evaluator_fingerprint"] == EVALUATOR_SHA
        assert receipt["dependency_sha256"] == DEPENDENCY_SHA
        assert receipt["environment_sha256"] == ENVIRONMENT_SHA
        assert receipt["runner_fingerprint"] == RUNNER_SHA
        assert receipt["generator_fingerprint"] == GENERATOR_SHA
        assert receipt["parent_id"] == candidate.parent_id
        assert receipt["generation"] == candidate.generation
        assert receipt["iteration"] == candidate.iteration
        assert receipt["island_id"] == candidate.island_id
        assert receipt["report_schema_version"] == candidate.evaluation.schema_version
        assert receipt["evaluator_id"] == candidate.evaluation.evaluator_id
        assert receipt["validity"] == candidate.evaluation.validity
        assert receipt["quality"] == candidate.evaluation.quality
        assert receipt["combined_score"] == candidate.evaluation.combined_score
        assert receipt["detailed_scores"] == candidate.evaluation.detailed_scores
        assert receipt["error_info"] == list(candidate.evaluation.error_info)
        digest = receipt.pop("receipt_sha256")
        assert digest == _canonical_digest(receipt)

        record = json.loads(record_path.read_text())
        assert record == line
        projection = record.get("integrity")
        if isinstance(projection, dict):
            assert projection["receipt_sha256"] == digest
            assert projection["source_sha256"] == receipt["source_sha256"]
        else:
            assert record["receipt_sha256"] == digest
            assert record["source_sha256"] == receipt["source_sha256"]

    state = archive.read_state()
    assert state["candidate_integrity_schema_version"] == "1"
    authority = state["candidate_integrity_authority"]
    assert authority["evaluator_kind"] == "callback"
    assert authority["evaluator_fingerprint"] == EVALUATOR_SHA
    assert authority["dependency_sha256"] == DEPENDENCY_SHA
    assert authority["environment_sha256"] == ENVIRONMENT_SHA
    assert authority["runner_fingerprint"] == RUNNER_SHA
    assert authority["generator_fingerprint"] == GENERATOR_SHA
    assert _SHA256(state["candidate_archive_sha256"])


def test_nested_source_sidecars_validate_and_resume_without_callbacks(
    tmp_path: Path,
) -> None:
    """Receipt/record sidecars follow a nested source directory on resume."""

    config = _config(max_rounds=1)
    generate_calls = {"count": 0}

    def generate(request):
        generate_calls["count"] += 1
        return CandidateDraft(
            f"iteration = {request.iteration}\n",
            filename="src/main.py",
        )

    first = _run(tmp_path, config=config, generate=generate)
    assert first.status == "completed"
    assert generate_calls["count"] == 2
    for candidate in CandidateArchive(tmp_path).records():
        candidate_root = tmp_path / candidate.code_path
        assert candidate_root.name == "main.py"
        assert candidate_root.parent.name == "src"
        assert (candidate_root.parent / "record.json").is_file()
        assert (candidate_root.parent / "receipt.json").is_file()

    def must_not_generate(request):
        pytest.fail(f"nested candidate resume generated iteration {request.iteration}")

    def must_not_evaluate(path, contract):
        del path, contract
        pytest.fail("nested candidate resume evaluated a candidate")

    resumed = _resume(
        tmp_path,
        config=config,
        generate=must_not_generate,
        evaluate=must_not_evaluate,
    )
    assert resumed.status == "completed"
    assert resumed.best_candidate_id == first.best_candidate_id
    assert generate_calls["count"] == 2


def test_candidate_archive_direct_persist_round_trip_with_nested_source(
    tmp_path: Path,
) -> None:
    """The public archive primitive publishes one self-consistent ordinary candidate."""

    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state({"contract_sha256": authority.contract_sha256})
    execution = archive.candidates_root / "candidate-0001" / "src" / "execution.json"
    execution.parent.mkdir(parents=True)
    execution.write_text('{"status":"succeeded"}\n', encoding="utf-8")
    candidate = archive.persist(
        CandidateDraft("answer = 42\n", filename="src/main.py"),
        candidate_id="candidate-0001",
        strategy="population",
        iteration=0,
        generation=0,
        parent_id=None,
        island_id=0,
        evaluation=_report(0.5),
        integrity_authority=authority,
    )

    source = tmp_path / candidate.code_path
    record = source.parent / "record.json"
    receipt = source.parent / "receipt.json"
    assert source.read_text(encoding="utf-8") == "answer = 42\n"
    assert json.loads(record.read_text(encoding="utf-8")) == candidate.to_dict()
    parsed_receipt = CandidateReceipt.from_dict(
        json.loads(receipt.read_text(encoding="utf-8"))
    )
    assert parsed_receipt.candidate_id == candidate.candidate_id
    assert parsed_receipt.execution_sha256 == hashlib.sha256(execution.read_bytes()).hexdigest()
    assert [json.loads(line) for line in archive.archive_path.read_text().splitlines()] == [
        candidate.to_dict()
    ]
    assert archive.validate_candidate_integrity(authority=authority) == (candidate,)


def test_state_atomic_write_rejects_symlinked_temporary_file(
    tmp_path: Path,
) -> None:
    archive = CandidateArchive(tmp_path)
    archive.root.mkdir(parents=True)
    target = tmp_path / "outside-state-target.json"
    original = b'{"outside":true}\n'
    target.write_bytes(original)
    temporary = archive.root / ".state.json.tmp"
    temporary.symlink_to(target)

    with pytest.raises(EvolutionError, match="evolution state persist failed"):
        archive.write_state({"schema_version": "1"})

    assert target.read_bytes() == original
    assert temporary.is_symlink()
    assert not archive.state_path.exists()


def test_stale_regular_state_temporary_allows_complete_pending_finalize_without_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(offspring_per_iteration=2)
    generate_calls = 0
    evaluate_calls = 0

    def generate(request):
        nonlocal generate_calls
        generate_calls += 1
        return CandidateDraft(
            f"iteration = {request.iteration}\ncall = {generate_calls}\n"
        )

    def evaluate(path, contract):
        nonlocal evaluate_calls
        del path, contract
        evaluate_calls += 1
        return _report(float(evaluate_calls))

    original_write_state = CandidateArchive.write_state

    def crash_before_completed_batch_state(self, payload):
        if (
            payload.get("status") == "running"
            and payload.get("iteration") == 1
            and payload.get("outcome_watermark") == 1
        ):
            raise RuntimeError("simulated crash before completed batch state")
        original_write_state(self, payload)

    monkeypatch.setattr(CandidateArchive, "write_state", crash_before_completed_batch_state)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _run(
            tmp_path,
            config=config,
            generate=generate,
            evaluate=evaluate,
        )

    archive = CandidateArchive(tmp_path)
    pending = archive.read_state()
    assert pending["iteration"] == 0
    assert pending["pending_offspring"] == {
        "schema_version": "1",
        "iteration": 1,
        "attempt_count": 2,
    }
    assert len(archive.offspring_outcomes()) == 2
    durable_before_resume = (
        archive.archive_path.read_bytes(),
        archive.offspring_outcomes_path.read_bytes(),
    )
    calls_before_resume = (generate_calls, evaluate_calls)
    stale_temporary = archive.root / ".state.json.tmp"
    stale_temporary.write_text('{"stale":true}\n', encoding="utf-8")

    monkeypatch.setattr(CandidateArchive, "write_state", original_write_state)
    resumed = _resume(
        tmp_path,
        config=config,
        generate=lambda request: pytest.fail("complete pending resume generated"),
        evaluate=lambda path, contract: pytest.fail("complete pending resume evaluated"),
    )

    assert resumed.status == "completed"
    assert resumed.iterations == 1
    assert (generate_calls, evaluate_calls) == calls_before_resume
    assert not stale_temporary.exists()
    assert durable_before_resume == (
        archive.archive_path.read_bytes(),
        archive.offspring_outcomes_path.read_bytes(),
    )
    final_state = archive.read_state()
    assert final_state["iteration"] == 1
    assert final_state["outcome_watermark"] == 1
    assert "pending_offspring" not in final_state


def test_population_direct_persist_rejects_seed_prefixed_id_before_write(
    tmp_path: Path,
) -> None:
    """Only the verified-seed transaction may publish a seed-prefixed population identity."""

    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state({"contract_sha256": authority.contract_sha256})

    with pytest.raises(EvolutionError, match="seed"):
        archive.persist(
            CandidateDraft("answer = 42\n", filename="src/main.py"),
            candidate_id="seed-forged",
            strategy="population",
            iteration=0,
            generation=0,
            parent_id=None,
            island_id=0,
            evaluation=_report(0.5),
            integrity_authority=authority,
        )

    candidate_root = archive.candidates_root / "seed-forged"
    assert not candidate_root.exists()
    assert not archive.archive_path.exists()


def test_direct_persist_rejects_marker_authority_drift_before_candidate_write(
    tmp_path: Path,
) -> None:
    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state(
        {
            "contract_sha256": authority.contract_sha256,
            "candidate_integrity_schema_version": "1",
            "candidate_integrity_authority": authority.to_dict(),
            "candidate_archive_sha256": _canonical_digest([]),
        }
    )
    changed = CandidateIntegrityAuthority.from_dict(
        {**authority.to_dict(), "runner_fingerprint": "f" * 64}
    )
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(
        EvolutionError,
        match="^ordinary_candidate_integrity_authority_mismatch$",
    ):
        archive.persist(
            CandidateDraft("answer = 42\n", filename="src/main.py"),
            candidate_id="candidate-0001",
            strategy="population",
            iteration=0,
            generation=0,
            parent_id=None,
            island_id=0,
            evaluation=_report(0.5),
            integrity_authority=changed,
        )

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (archive.candidates_root / "candidate-0001").exists()
    assert not archive.archive_path.exists()


@pytest.mark.parametrize(
    "credential_key",
    [
        "sk-abcdefghijklmnop",
        "api_key",
        "client_secret",
        "access_token",
    ],
)
def test_credential_like_metadata_key_is_rejected_before_candidate_write(
    tmp_path: Path,
    credential_key: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state({"contract_sha256": authority.contract_sha256})
    before = archive.state_path.read_bytes()

    with pytest.raises(EvolutionError, match="^ordinary_candidate_metadata_invalid$"):
        archive.persist(
            CandidateDraft(
                "answer = 42\n",
                metadata={credential_key: "plain-secret-must-never-persist"},
            ),
            candidate_id="candidate-0001",
            strategy="population",
            iteration=0,
            generation=0,
            parent_id=None,
            island_id=0,
            evaluation=_report(0.5),
            integrity_authority=authority,
        )

    assert archive.state_path.read_bytes() == before
    assert not (archive.candidates_root / "candidate-0001").exists()
    assert not archive.archive_path.exists()
    durable = b"".join(
        path.read_bytes()
        for path in (tmp_path / "evolution").rglob("*")
        if path.is_file()
    )
    assert credential_key.encode("utf-8") not in durable
    assert b"plain-secret-must-never-persist" not in durable


@pytest.mark.parametrize("temporary_kind", ["dangling_symlink", "hardlink"])
def test_execution_temporary_link_is_not_followed_or_truncated(
    tmp_path: Path,
    temporary_kind: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    temporary = workspace / ".execution.json.tmp"
    outside = tmp_path / "outside-execution-target.json"
    original = b'{"outside":true}\n'
    if temporary_kind == "dangling_symlink":
        temporary.symlink_to(outside)
    else:
        outside.write_bytes(original)
        os.link(outside, temporary)

    with pytest.raises(
        EvolutionError,
        match="^candidate execution temporary evidence must not be a symlink$",
    ):
        evolution_module._write_execution_evidence(
            workspace,
            CandidateExecution(status="succeeded", exit_code=0, duration_ms=1),
        )

    assert not (workspace / "execution.json").exists()
    if temporary_kind == "dangling_symlink":
        assert temporary.is_symlink()
        assert not outside.exists()
    else:
        assert temporary.read_bytes() == outside.read_bytes() == original
        assert temporary.stat().st_ino == outside.stat().st_ino


@pytest.mark.parametrize("artifact", ["archive", "offspring_outcomes"])
def test_append_only_file_external_hardlink_is_not_appended(
    tmp_path: Path,
    artifact: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state({"contract_sha256": authority.contract_sha256})
    outside = tmp_path / f"outside-{artifact}.jsonl"
    original = b"\n"
    outside.write_bytes(original)
    linked = (
        archive.archive_path
        if artifact == "archive"
        else archive.offspring_outcomes_path
    )
    os.link(outside, linked)

    if artifact == "archive":
        with pytest.raises(EvolutionError, match="private regular file"):
            archive.persist(
                CandidateDraft("answer = 42\n"),
                candidate_id="candidate-0001",
                strategy="population",
                iteration=0,
                generation=0,
                parent_id=None,
                island_id=0,
                evaluation=_report(0.5),
                integrity_authority=authority,
            )
    else:
        with pytest.raises(EvolutionError, match="^population_outcomes_invalid$"):
            archive.append_offspring_outcome(
                OffspringOutcome(1, 0, 0, "candidate_failed")
            )

    assert linked.read_bytes() == outside.read_bytes() == original
    assert linked.stat().st_ino == outside.stat().st_ino


@pytest.mark.parametrize("artifact", ["archive", "offspring_outcomes"])
def test_append_only_file_never_grows_beyond_reader_limit(
    tmp_path: Path,
    artifact: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    archive._ensure_layout()
    path = (
        archive.archive_path
        if artifact == "archive"
        else archive.offspring_outcomes_path
    )
    blank_line = b" " * (MAX_ARCHIVE_LINE_BYTES - 1) + b"\n"
    original = blank_line * (
        evolution_module.MAX_ARCHIVE_BYTES // MAX_ARCHIVE_LINE_BYTES
    )
    assert len(original) == evolution_module.MAX_ARCHIVE_BYTES
    path.write_bytes(original)

    if artifact == "archive":
        with pytest.raises(EvolutionError, match="exceeds the bounded size"):
            archive.persist(
                CandidateDraft("answer = 42\n"),
                candidate_id="candidate-0001",
                strategy="population",
                iteration=0,
                generation=0,
                parent_id=None,
                island_id=0,
                evaluation=_report(0.5),
                integrity_authority=_authority(),
            )
        assert archive.records() == []
    else:
        with pytest.raises(EvolutionError, match="^population_outcomes_invalid$"):
            archive.append_offspring_outcome(
                OffspringOutcome(1, 0, 0, "candidate_failed")
            )
        assert archive.offspring_outcomes() == ()

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("rollback_fsync_fails", "expected_error", "sidecars_remain"),
    [
        (False, "candidate_failed", False),
        (True, "ordinary_candidate_archive_publication_unknown", True),
    ],
)
def test_archive_fsync_failure_rolls_back_or_preserves_complete_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rollback_fsync_fails: bool,
    expected_error: str,
    sidecars_remain: bool,
) -> None:
    archive_path = tmp_path / "evolution" / "archive.jsonl"
    original_fsync = os.fsync
    archive_fsync_calls = 0

    def fail_archive_fsync(descriptor: int) -> None:
        nonlocal archive_fsync_calls
        try:
            opened = os.fstat(descriptor)
            current = archive_path.stat()
        except OSError:
            original_fsync(descriptor)
            return
        if (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino):
            archive_fsync_calls += 1
            if archive_fsync_calls <= (2 if rollback_fsync_fails else 1):
                raise OSError("simulated archive fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_archive_fsync)
    if rollback_fsync_fails:
        with pytest.raises(EvolutionError, match=f"^{expected_error}$"):
            _run(tmp_path)
    else:
        result = _run(tmp_path)
        assert result.status == "failed"
        assert result.error == expected_error
    assert archive_fsync_calls == 2
    assert archive_path.is_file()
    assert archive_path.read_bytes() == b""
    candidate_root = tmp_path / "evolution" / "candidates" / "candidate-0001"
    assert candidate_root.exists() is sidecars_remain
    for name in ("candidate.py", "record.json", "receipt.json"):
        assert (candidate_root / name).is_file() is sidecars_remain
    if sidecars_remain:
        assert json.loads((candidate_root / "record.json").read_text(encoding="utf-8"))
        assert CandidateReceipt.from_dict(
            json.loads((candidate_root / "receipt.json").read_text(encoding="utf-8"))
        ).candidate_id == "candidate-0001"


@pytest.mark.parametrize("artifact", ["archive", "offspring_outcomes"])
def test_append_rollback_rejects_replaced_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    path = (
        archive.archive_path
        if artifact == "archive"
        else archive.offspring_outcomes_path
    )
    displaced = path.with_name(f"{path.name}.displaced")
    original_fsync = os.fsync
    replaced = False

    def replace_entry_after_first_file_fsync(descriptor: int) -> None:
        nonlocal replaced
        try:
            opened = os.fstat(descriptor)
            current = path.stat()
        except OSError:
            original_fsync(descriptor)
            return
        original_fsync(descriptor)
        if (
            not replaced
            and opened.st_size > 0
            and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
        ):
            content = path.read_bytes()
            os.replace(path, displaced)
            path.write_bytes(content)
            replaced = True

    monkeypatch.setattr(os, "fsync", replace_entry_after_first_file_fsync)
    if artifact == "archive":
        with pytest.raises(
            EvolutionError,
            match="^ordinary_candidate_archive_publication_unknown$",
        ):
            _run(tmp_path)
        candidate_root = archive.candidates_root / "candidate-0001"
        assert all(
            (candidate_root / name).is_file()
            for name in ("candidate.py", "record.json", "receipt.json")
        )
    else:
        with pytest.raises(
            EvolutionError,
            match="^population_outcome_publication_unknown$",
        ):
            archive.append_offspring_outcome(
                OffspringOutcome(1, 0, 0, "candidate_failed")
            )

    assert replaced
    assert path.is_file() and path.read_bytes()
    assert displaced.is_file() and displaced.read_bytes() == b""


def test_fresh_candidate_id_reuse_discards_unpublished_staging_tree(
    tmp_path: Path,
) -> None:
    stale_root = tmp_path / "evolution" / "candidates" / "candidate-0001"
    stale_root.mkdir(parents=True)
    (stale_root / "execution.json").write_text(
        '{"stale":"sk-must-not-be-bound-123456"}\n',
        encoding="utf-8",
    )
    for name in ("record.json", "receipt.json"):
        (stale_root / name).write_text('{"stale":true}\n', encoding="utf-8")

    result = _run(tmp_path)

    assert result.status == "completed"
    source, record, receipt = _candidate_files(tmp_path, "candidate-0001")
    assert source.read_text(encoding="utf-8") == "iteration = 0\n"
    assert record.is_file()
    parsed = CandidateReceipt.from_dict(json.loads(receipt.read_text(encoding="utf-8")))
    assert parsed.execution_sha256 is None
    assert not (source.parent / "execution.json").exists()
    durable = b"".join(
        path.read_bytes()
        for path in (tmp_path / "evolution").rglob("*")
        if path.is_file()
    )
    assert b"sk-must-not-be-bound" not in durable


def test_resume_accepts_missing_execution_when_receipt_is_unbound(tmp_path: Path) -> None:
    """A callback candidate need not have execution evidence when its receipt omits the digest."""

    first = _run(tmp_path)
    for candidate in CandidateArchive(tmp_path).records():
        source = tmp_path / candidate.code_path
        receipt = CandidateReceipt.from_dict(
            json.loads((source.parent / "receipt.json").read_text(encoding="utf-8"))
        )
        assert receipt.execution_sha256 is None
        assert not (source.parent / "execution.json").exists()

    resumed = _resume(
        tmp_path,
        generate=lambda request: pytest.fail("terminal resume generated"),
        evaluate=lambda path, contract: pytest.fail("terminal resume evaluated"),
    )
    assert resumed.status == "completed"
    assert resumed.best_candidate_id == first.best_candidate_id


@pytest.mark.parametrize(
    "invalid_execution",
    [
        "symlink",
        "oversized",
        "directory",
        pytest.param(
            "fifo",
            marks=pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable"),
        ),
    ],
)
def test_invalid_execution_is_rejected_before_fresh_offspring_publication(
    tmp_path: Path,
    invalid_execution: str,
) -> None:
    """Evaluator-created evidence must be bounded and regular before a receipt is issued."""

    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        if "iteration = 1" not in path.read_text(encoding="utf-8"):
            return _report(0.5)
        execution = path.parent / "execution.json"
        if invalid_execution == "symlink":
            target = tmp_path / "execution-target.json"
            target.write_text('{"status":"succeeded"}\n', encoding="utf-8")
            execution.symlink_to(target)
        elif invalid_execution == "oversized":
            execution.write_bytes(b"x" * (MAX_ARCHIVE_LINE_BYTES + 1))
        elif invalid_execution == "directory":
            execution.mkdir()
        else:
            os.mkfifo(execution)
        return _report(0.75)

    result = _run(tmp_path, evaluate=evaluate)
    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert [item.candidate_id for item in archive.records()] == ["candidate-0001"]
    outcomes = archive.offspring_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].code == "candidate_failed"
    assert outcomes[0].candidate_id is None
    rejected_root = archive.candidates_root / "candidate-0002"
    assert not rejected_root.exists()
    assert not (rejected_root / "record.json").exists()
    assert not (rejected_root / "receipt.json").exists()


@pytest.mark.parametrize("execution_state", ["missing", "digest_mismatch"])
def test_direct_persist_rejects_invalid_claimed_execution_before_publication(
    tmp_path: Path,
    execution_state: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    authority = _authority()
    archive.write_state({"contract_sha256": authority.contract_sha256})
    source = archive.candidates_root / "candidate-0001" / "src" / "main.py"
    if execution_state == "digest_mismatch":
        execution = source.parent / "execution.json"
        execution.parent.mkdir(parents=True)
        execution.write_text('{"status":"succeeded"}\n', encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(EvolutionError, match="^ordinary_candidate_execution_mismatch$"):
        archive.persist(
            CandidateDraft("answer = 42\n", filename="src/main.py"),
            candidate_id="candidate-0001",
            strategy="population",
            iteration=0,
            generation=0,
            parent_id=None,
            island_id=0,
            evaluation=_report(0.5),
            integrity_authority=authority,
            execution_sha256="f" * 64,
        )

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not source.exists()
    assert not archive.archive_path.exists()
    assert not (source.parent / "record.json").exists()
    assert not (source.parent / "receipt.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("tamper", ["symlink", "oversized", "non_regular", "missing"])
def test_resume_rejects_invalid_bound_execution_before_callbacks(
    tmp_path: Path,
    tamper: str,
) -> None:
    """Bound execution evidence is a regular, bounded, digest-matching file on resume."""

    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        (path.parent / "execution.json").write_text(
            json.dumps({"status": "succeeded", "candidate": path.name}) + "\n",
            encoding="utf-8",
        )
        return _report(0.5)

    _run(tmp_path, evaluate=evaluate)
    source, _, receipt_path = _candidate_files(tmp_path, "candidate-0001")
    execution = source.parent / "execution.json"
    receipt = CandidateReceipt.from_dict(json.loads(receipt_path.read_text(encoding="utf-8")))
    assert receipt.execution_sha256 == hashlib.sha256(execution.read_bytes()).hexdigest()

    if tamper == "symlink":
        target = execution.with_name("execution.target.json")
        target.write_bytes(execution.read_bytes())
        execution.unlink()
        execution.symlink_to(target)
    elif tamper == "oversized":
        execution.write_bytes(b"x" * (MAX_ARCHIVE_LINE_BYTES + 1))
    elif tamper == "non_regular":
        execution.unlink()
        execution.mkdir()
    else:
        execution.unlink()

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("execution-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("execution-tampered resume evaluated")

    with pytest.raises(EvolutionError):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_oversized_source_after_evaluation_is_rejected_without_unbounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unbounded_reads: list[Path] = []
    original_read_bytes = Path.read_bytes

    def reject_unbounded_source_read(path: Path) -> bytes:
        if path.name == "candidate.py" and path.is_file() and path.stat().st_size > MAX_SOURCE_BYTES:
            unbounded_reads.append(path)
            raise AssertionError("oversized candidate source used Path.read_bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_source_read)

    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        if "iteration = 1" in path.read_text(encoding="utf-8"):
            path.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
        return _report(0.5)

    result = _run(tmp_path, evaluate=evaluate)
    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert [candidate.candidate_id for candidate in archive.records()] == ["candidate-0001"]
    assert [outcome.code for outcome in archive.offspring_outcomes()] == ["candidate_failed"]
    assert not (archive.candidates_root / "candidate-0002").exists()
    assert unbounded_reads == []


def test_resume_rejects_oversized_source_before_callbacks_without_unbounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(tmp_path)
    source, _, _ = _candidate_files(tmp_path, "candidate-0001")
    source.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    unbounded_reads: list[Path] = []
    original_read_bytes = Path.read_bytes

    def reject_unbounded_source_read(path: Path) -> bytes:
        if path == source:
            unbounded_reads.append(path)
            raise AssertionError("oversized candidate source used Path.read_bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_source_read)
    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("oversized-source resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("oversized-source resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_source_mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}
    assert unbounded_reads == []


@pytest.mark.parametrize(
    "filename",
    [
        "record.json",
        "receipt.json",
        "execution.json",
        ".record.json.tmp",
        ".receipt.json.tmp",
        ".execution.json.tmp",
        "src/record.json",
        "src/execution.json",
    ],
)
def test_integrity_sidecar_names_are_reserved_for_candidate_sources(
    tmp_path: Path,
    filename: str,
) -> None:
    archive = CandidateArchive(tmp_path)
    with pytest.raises(EvolutionError, match="candidate filename is reserved"):
        archive.candidate_source_path("candidate-0001", filename)


@pytest.mark.parametrize(
    "target",
    ["source", "record", "receipt", "candidate_dir", "nested_intermediate"],
)
def test_resume_rejects_symlinked_candidate_evidence_before_callbacks(
    tmp_path: Path,
    target: str,
) -> None:
    """Neither a sidecar nor any source path component may be redirected by a link."""

    nested = target == "nested_intermediate"
    generate = (
        (lambda request: CandidateDraft(f"iteration = {request.iteration}\n", filename="src/main.py"))
        if nested
        else None
    )
    _run(tmp_path, generate=generate)

    candidate_dir = tmp_path / "evolution" / "candidates" / "candidate-0001"
    source_dir = candidate_dir / "src" if nested else candidate_dir
    if target in {"source", "record", "receipt"}:
        name = {
            "source": "candidate.py",
            "record": "record.json",
            "receipt": "receipt.json",
        }[target]
        original = source_dir / name
        replacement = source_dir / f"{name}.target"
        replacement.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(replacement)
    elif target == "candidate_dir":
        replacement = candidate_dir.with_name("candidate-0001-target")
        candidate_dir.rename(replacement)
        candidate_dir.symlink_to(replacement, target_is_directory=True)
    else:
        replacement = candidate_dir / "src-target"
        source_dir.rename(replacement)
        source_dir.symlink_to(replacement, target_is_directory=True)

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        calls["generate"] += 1
        pytest.fail(f"symlink-tampered resume generated iteration {request.iteration}")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("symlink-tampered resume evaluated a candidate")

    with pytest.raises(EvolutionError, match="symlink"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def _SHA256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


@pytest.mark.parametrize("field", ["combined_score", "validity", "source_sha256", "receipt_sha256"])
def test_receipt_tamper_fails_before_resume_callbacks(tmp_path: Path, field: str) -> None:
    _run(tmp_path)
    receipt_path = tmp_path / "evolution" / "candidates" / "candidate-0001" / "receipt.json"
    payload = json.loads(receipt_path.read_text())
    if field == "combined_score":
        payload[field] = 0.75
    elif field == "validity":
        payload[field] = 0
    elif field == "source_sha256":
        payload[field] = "f" * 64
    else:
        payload[field] = "e" * 64
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n")

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        calls["generate"] += 1
        pytest.fail(f"resume generated iteration {request.iteration}")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("resume evaluated a tampered candidate")

    with pytest.raises(EvolutionError):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_receipt_error_message_tamper_fails_before_resume_callbacks(
    tmp_path: Path,
) -> None:
    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        if "iteration = 0" in path.read_text(encoding="utf-8"):
            return _report(0.5)
        return _report(0.5, valid=0)

    _run(tmp_path, evaluate=evaluate)
    receipt_path = tmp_path / "evolution" / "candidates" / "candidate-0002" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["error_info"] == [
        {"code": "invalid", "message": "local evaluator reported an error"}
    ]
    receipt["error_info"][0]["message"] = "tampered evaluator explanation"
    original_digest = receipt["receipt_sha256"]
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["receipt_sha256"] == original_digest

    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("receipt-message-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("receipt-message-tampered resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_receipt_invalid$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    ("authority_field", "override"),
    [
        ("evaluator_fingerprint", "a" * 64),
        ("generator_fingerprint", "b" * 64),
        ("runner_fingerprint", "c" * 64),
        ("dependency_sha256", "d" * 64),
        ("environment_sha256", "e" * 64),
    ],
)
def test_resume_rejects_authority_drift_before_callbacks(
    tmp_path: Path,
    authority_field: str,
    override: str,
) -> None:
    _run(tmp_path)
    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("resume generated after authority drift")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("resume evaluated after authority drift")

    with pytest.raises(EvolutionError):
        _resume(
            tmp_path,
            config=_config(**{authority_field: override}),
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private evaluator prose sk-test-secret"),
        TimeoutError("private timeout sk-test-secret"),
        WorkerUnknownError("private worker uncertainty sk-test-secret"),
    ],
    ids=["run-failed", "timeout", "worker-unknown"],
)
def test_failed_offspring_has_no_receipt_or_candidate(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    def evaluate(path, contract):
        del contract
        if "iteration = 0" in path.read_text(encoding="utf-8"):
            return _report(1.0)
        raise failure

    result = _run(tmp_path, evaluate=evaluate)
    assert result.status == "failed"
    archive = CandidateArchive(tmp_path)
    records = archive.records()
    assert len(records) == 1
    assert not (archive.candidates_root / "candidate-0002").exists()
    assert not (archive.candidates_root / "candidate-0002" / "receipt.json").exists()
    outcomes = archive.offspring_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].candidate_id is None
    assert outcomes[0].code in {"run_failed", "evaluator_timeout", "worker_unknown"}
    durable = b"".join(path.read_bytes() for path in (tmp_path / "evolution").rglob("*") if path.is_file())
    assert b"private evaluator prose" not in durable
    assert b"sk-test-secret" not in durable


@pytest.mark.parametrize("artifact", ["source", "record", "archive"])
def test_published_artifact_tamper_fails_closed_before_resume_callbacks(
    tmp_path: Path,
    artifact: str,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    candidate_root = root / "candidates" / "candidate-0001"
    if artifact == "source":
        source = candidate_root / "candidate.py"
        original = source.read_bytes()
        assert original
        replacement = bytearray(original)
        replacement[-1] = ord("9") if replacement[-1] != ord("9") else ord("8")
        source.write_bytes(bytes(replacement))
    elif artifact == "record":
        record_path = candidate_root / "record.json"
        record = json.loads(record_path.read_text())
        record["evaluation"]["combined_score"] = 0.75
        record_path.write_text(json.dumps(record, sort_keys=True) + "\n")
    else:
        archive_path = root / "archive.jsonl"
        lines = [json.loads(line) for line in archive_path.read_text().splitlines()]
        lines[0]["evaluation"]["combined_score"] = 0.75
        archive_path.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in lines))

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("resume generated after artifact tamper")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("resume evaluated after artifact tamper")

    with pytest.raises(EvolutionError):
        _resume(tmp_path, generate=must_not_generate, evaluate=must_not_evaluate)
    assert calls == {"generate": 0, "evaluate": 0}


def test_terminal_archive_child_before_parent_fails_lineage_after_digest_rewrite(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    assert len(records) == 2
    records.reverse()
    assert records[0]["parent_id"] == records[1]["candidate_id"]
    archive_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_archive_sha256"] = _canonical_digest(records)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("archive-order-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("archive-order-tampered resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_lineage_mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_json_int_float_tamper_cannot_use_python_numeric_equality(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    initial = next(record for record in records if record["iteration"] == 0)
    assert initial["evaluation"]["validity"] == 1
    initial["evaluation"]["validity"] = 1.0
    candidate_root = root / "candidates" / initial["candidate_id"]
    (candidate_root / "record.json").write_text(
        json.dumps(initial, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_archive_sha256"] = _canonical_digest(records)
    state["outcome_archive_baseline_sha256"] = _canonical_digest([initial])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("numeric-type-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("numeric-type-tampered resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_integrity_mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


def test_resume_rejects_candidate_island_outside_configured_range(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    initial = next(record for record in records if record["iteration"] == 0)
    candidate_root = root / "candidates" / initial["candidate_id"]
    receipt_path = candidate_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["island_id"] = 1
    receipt["receipt_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    initial["island_id"] = 1
    initial["receipt_sha256"] = receipt["receipt_sha256"]
    initial["integrity"]["island_id"] = 1
    initial["integrity"]["receipt_sha256"] = receipt["receipt_sha256"]
    (candidate_root / "record.json").write_text(
        json.dumps(initial, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_archive_sha256"] = _canonical_digest(records)
    state["outcome_archive_baseline_sha256"] = _canonical_digest([initial])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("out-of-range-island resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("out-of-range-island resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_lineage_mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    "tamper",
    [
        "partial-integrity",
        "unknown-field",
        "evaluation-missing-schema",
        "evaluation-unknown-field",
    ],
)
def test_modern_archive_record_shape_tamper_fails_before_callbacks(
    tmp_path: Path,
    tamper: str,
) -> None:
    _run(tmp_path)
    archive_path = tmp_path / "evolution" / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    if tamper == "partial-integrity":
        records[0].pop("receipt_sha256")
    elif tamper == "unknown-field":
        records[0]["unexpected"] = True
    elif tamper == "evaluation-missing-schema":
        records[0]["evaluation"].pop("schema_version")
    else:
        records[0]["evaluation"]["unexpected"] = True
    archive_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("record-shape-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("record-shape-tampered resume evaluated")

    with pytest.raises(EvolutionError, match="ordinary_candidate_record_invalid"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_evaluator_source_rewrite_is_not_admitted_as_a_scored_candidate(tmp_path: Path) -> None:
    def evaluate(path, contract):
        del contract
        if "iteration = 0" in path.read_text(encoding="utf-8"):
            return _report(0.5)
        path.write_text("iteration = 9\n", encoding="utf-8")
        return _report(0.9)

    result = _run(tmp_path, evaluate=evaluate)
    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert [item.code for item in archive.offspring_outcomes()] == ["candidate_failed"]
    # The evaluator rewrote the staged source, so no ordinary receipt may claim the attempted
    # offspring.  The initial candidate remains the only durable scored record.
    records = archive.records()
    assert len(records) == 1
    assert not (archive.candidates_root / "candidate-0002" / "receipt.json").exists()


def test_evaluator_source_rewrite_then_restore_is_not_admitted(
    tmp_path: Path,
) -> None:
    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        original = path.read_bytes()
        if b"iteration = 0" in original:
            return _report(0.5)
        path.write_text("iteration = rewritten for scoring\n", encoding="utf-8")
        assert path.read_bytes() != original
        path.write_bytes(original)
        return _report(0.9)

    result = _run(tmp_path, evaluate=evaluate)

    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert [candidate.candidate_id for candidate in archive.records()] == [
        "candidate-0001"
    ]
    assert [outcome.code for outcome in archive.offspring_outcomes()] == [
        "candidate_failed"
    ]
    attempted = archive.candidates_root / "candidate-0002"
    assert not attempted.exists()
    assert not (attempted / "receipt.json").exists()


def test_evaluator_report_mutation_after_return_cannot_change_durable_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returned_report = _report(0.5)
    permit_mutation = threading.Event()
    mutation_finished = threading.Event()

    def mutate_returned_report() -> None:
        if permit_mutation.wait(timeout=5):
            returned_report.detailed_scores["quality"]["value"] = 9.0
            mutation_finished.set()

    mutator = threading.Thread(target=mutate_returned_report, daemon=True)

    def evaluate(path, contract):
        del contract
        if path.parent.name == "candidate-0001":
            mutator.start()
            return returned_report
        return _report(0.75)

    original_persist = CandidateArchive.persist

    def persist_after_background_mutation(self, draft, *args, **kwargs):
        if kwargs.get("candidate_id") == "candidate-0001":
            permit_mutation.set()
            assert mutation_finished.wait(timeout=5)
        return original_persist(self, draft, *args, **kwargs)

    monkeypatch.setattr(CandidateArchive, "persist", persist_after_background_mutation)
    result = _run(tmp_path, evaluate=evaluate)
    mutator.join(timeout=5)

    assert result.status == "completed"
    assert not mutator.is_alive()
    candidate = CandidateArchive(tmp_path).records()[0]
    expected_scores = {"quality": {"value": 0.5, "direction": "maximize"}}
    assert candidate.evaluation.detailed_scores == expected_scores
    source = tmp_path / candidate.code_path
    receipt = CandidateReceipt.from_dict(
        json.loads((source.parent / "receipt.json").read_text(encoding="utf-8"))
    )
    assert receipt.detailed_scores == expected_scores
    assert json.loads((source.parent / "record.json").read_text(encoding="utf-8"))[
        "evaluation"
    ]["detailed_scores"] == expected_scores


@pytest.mark.parametrize("artifact", ["source", "execution"])
def test_evaluator_background_mutation_during_publication_is_not_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    record_boundary = threading.Event()
    mutation_finished = threading.Event()
    mutators: list[threading.Thread] = []

    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        if path.parent.name == "candidate-0001":
            return _report(0.5)
        target = path
        if artifact == "execution":
            target = path.parent / "execution.json"
            target.write_text('{"status":"before"}\n', encoding="utf-8")

        def mutate_after_snapshot() -> None:
            if record_boundary.wait(timeout=5):
                target.write_text("mutated during publication\n", encoding="utf-8")
                mutation_finished.set()

        mutator = threading.Thread(target=mutate_after_snapshot, daemon=True)
        mutators.append(mutator)
        mutator.start()
        return _report(0.9)

    original_write = CandidateArchive._atomic_write_bytes

    def write_after_mutation(path: Path, content: bytes, *, error: str) -> None:
        if path.name == "record.json" and path.parent.name == "candidate-0002":
            record_boundary.set()
            assert mutation_finished.wait(timeout=5)
        original_write(path, content, error=error)

    monkeypatch.setattr(
        CandidateArchive,
        "_atomic_write_bytes",
        staticmethod(write_after_mutation),
    )
    result = _run(tmp_path, evaluate=evaluate)
    for mutator in mutators:
        mutator.join(timeout=5)

    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert [candidate.candidate_id for candidate in archive.records()] == [
        "candidate-0001"
    ]
    assert [outcome.code for outcome in archive.offspring_outcomes()] == [
        "candidate_failed"
    ]
    assert not (archive.candidates_root / "candidate-0002").exists()


def test_all_invalid_population_retries_without_parent_and_finishes_with_empty_active(
    tmp_path: Path,
) -> None:
    requests = []

    def generate(request):
        requests.append(request)
        return CandidateDraft(f"iteration = {request.iteration}\n")

    result = _run(
        tmp_path,
        generate=generate,
        evaluate=lambda path, contract: _report(0.0, valid=0),
    )

    archive = CandidateArchive(tmp_path)
    records = archive.records()
    assert [request.iteration for request in requests] == [0, 1]
    assert requests[1].parent is None
    assert [candidate.iteration for candidate in records] == [0, 1]
    assert records[1].parent_id is None
    assert records[1].generation == 0
    assert result.status == "failed"
    assert result.valid_candidates == 0
    assert result.best_candidate_id is None
    state = archive.read_state()
    assert state["status"] == "failed"
    assert state["active_ids"] == {"0": []}
    assert state["best_candidate_id"] is None


def test_source_rewrite_after_staging_before_first_snapshot_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_atomic_write = CandidateArchive._atomic_write_bytes
    rewritten_paths: list[Path] = []

    def write_then_rewrite(path: Path, content: bytes, *, error: str) -> None:
        original_atomic_write(path, content, error=error)
        if error == "ordinary_candidate_source_changed":
            path.write_text("rewritten before first snapshot\n", encoding="utf-8")
            rewritten_paths.append(path)

    monkeypatch.setattr(
        CandidateArchive,
        "_atomic_write_bytes",
        staticmethod(write_then_rewrite),
    )
    evaluate_calls = 0

    def must_not_evaluate(path, contract):
        nonlocal evaluate_calls
        del path, contract
        evaluate_calls += 1
        pytest.fail("rewritten staged source reached the evaluator")

    result = _run(tmp_path, evaluate=must_not_evaluate)

    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert result.error == "candidate_failed"
    assert rewritten_paths
    assert evaluate_calls == 0
    assert archive.records() == []
    assert not archive.offspring_outcomes()
    assert not any(archive.candidates_root.iterdir())


def test_resume_rejects_an_unknown_parent_even_when_all_projections_are_rewritten(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    candidate_id = "candidate-0002"
    candidate_root = root / "candidates" / candidate_id
    receipt_path = candidate_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["parent_id"] = "candidate-9999"
    receipt_payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = _canonical_digest(receipt_payload)
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")

    archive_path = root / "archive.jsonl"
    lines = [json.loads(line) for line in archive_path.read_text().splitlines()]
    target = next(item for item in lines if item["candidate_id"] == candidate_id)
    target["parent_id"] = "candidate-9999"
    target["receipt_sha256"] = receipt["receipt_sha256"]
    target["integrity"]["parent_id"] = "candidate-9999"
    target["integrity"]["receipt_sha256"] = receipt["receipt_sha256"]
    record_path = candidate_root / "record.json"
    record_path.write_text(json.dumps(target, sort_keys=True) + "\n")
    archive_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in lines))

    state_path = root / "state.json"
    state = json.loads(state_path.read_text())
    state["candidate_archive_sha256"] = _canonical_digest(lines)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n")

    with pytest.raises(EvolutionError):
        _resume(
            tmp_path,
            generate=lambda request: pytest.fail("lineage-tampered resume generated"),
            evaluate=lambda path, contract: pytest.fail("lineage-tampered resume evaluated"),
        )


def test_resume_rejects_invalid_parent_after_all_projections_are_rewritten(
    tmp_path: Path,
) -> None:
    def evaluate(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        return (
            _report(0.0, valid=0)
            if "iteration = 0" in path.read_text(encoding="utf-8")
            else _report(0.5)
        )

    result = _run(tmp_path, evaluate=evaluate)
    assert result.status == "completed"
    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    invalid_parent = next(item for item in records if item["evaluation"]["validity"] == 0)
    target = next(item for item in records if item["evaluation"]["validity"] == 1)
    assert target["parent_id"] is None and target["generation"] == 0

    target_root = root / "candidates" / target["candidate_id"]
    receipt_path = target_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["parent_id"] = invalid_parent["candidate_id"]
    receipt["generation"] = 1
    receipt["receipt_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")

    target["parent_id"] = invalid_parent["candidate_id"]
    target["generation"] = 1
    target["receipt_sha256"] = receipt["receipt_sha256"]
    target["integrity"]["parent_id"] = invalid_parent["candidate_id"]
    target["integrity"]["generation"] = 1
    target["integrity"]["receipt_sha256"] = receipt["receipt_sha256"]
    (target_root / "record.json").write_text(
        json.dumps(target, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_archive_sha256"] = _canonical_digest(records)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("invalid-parent resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("invalid-parent resume evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_lineage_mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


def test_seed_prefixed_ordinary_record_cannot_bypass_integrity_gate(
    tmp_path: Path,
) -> None:
    """A seed-looking ID is not verified-seed admission evidence."""

    cancelled_checks = 0

    def cancel_after_initial_candidate() -> bool:
        nonlocal cancelled_checks
        cancelled_checks += 1
        return cancelled_checks > 1

    context = EvolutionContext(
        _contract(),
        tmp_path,
        lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
        lambda path, supplied: _report(0.5),
        _config(),
        cancelled=cancel_after_initial_candidate,
    )
    result = PopulationStrategy(context).run()
    assert result.status == "cancelled"

    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    assert len(records) == 1
    records[0]["candidate_id"] = "seed-forged"
    archive_path.write_text(
        json.dumps(records[0], ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    state_path = root / "state.json"
    state = json.loads(state_path.read_text())
    state["active_ids"] = {"0": ["seed-forged"]}
    state["best_candidate_id"] = "seed-forged"
    # This is the digest an implementation that mistakes the prefix for seed admission would
    # compute after excluding the forged record from ordinary candidate state.
    state["candidate_archive_sha256"] = _canonical_digest([])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        calls["generate"] += 1
        pytest.fail(f"seed-like forged resume generated iteration {request.iteration}")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("seed-like forged resume evaluated a candidate")

    with pytest.raises(EvolutionError):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_seed_marker_without_commit_evidence_cannot_bypass_integrity_gate(
    tmp_path: Path,
) -> None:
    cancelled_checks = 0

    def cancel_after_initial_candidate() -> bool:
        nonlocal cancelled_checks
        cancelled_checks += 1
        return cancelled_checks > 1

    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
            lambda path, supplied: _report(0.5),
            _config(),
            cancelled=cancel_after_initial_candidate,
        )
    ).run()
    assert result.status == "cancelled"

    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    record = json.loads(archive_path.read_text(encoding="utf-8"))
    record["candidate_id"] = "seed-forged"
    record["metadata"] = {"seed_handoff": {"schema_version": "1"}}
    archive_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["active_ids"] = {"0": ["seed-forged"]}
    state["best_candidate_id"] = "seed-forged"
    state["candidate_archive_sha256"] = _canonical_digest([])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("forged seed marker resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("forged seed marker resume evaluated")

    with pytest.raises(
        EvolutionError,
        match="^verified_seed_resume_requires_initial_seeds$",
    ):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    [
        ("authority", "ordinary_candidate_integrity_authority_mismatch"),
        ("schema-version", "ordinary_candidate_integrity_state_invalid"),
        ("missing-config", "configuration does not match"),
        ("missing-schema", "ordinary_candidate_integrity_state_invalid"),
        ("missing-authority", "ordinary_candidate_integrity_state_invalid"),
        ("missing-digest", "ordinary_candidate_integrity_state_invalid"),
        ("missing-all", LEGACY_CANDIDATE_INTEGRITY_ERROR),
    ],
)
def test_zero_candidate_state_tamper_fails_before_callbacks(
    tmp_path: Path,
    tamper: str,
    expected_error: str,
) -> None:
    context = EvolutionContext(
        _contract(),
        tmp_path,
        lambda request: pytest.fail("cancelled run generated"),
        lambda path, supplied: pytest.fail("cancelled run evaluated"),
        _config(),
        cancelled=lambda: True,
    )
    result = PopulationStrategy(context).run()
    assert result.status == "cancelled"
    assert CandidateArchive(tmp_path).records() == []

    state_path = tmp_path / "evolution" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    marker_by_tamper = {
        "missing-schema": "candidate_integrity_schema_version",
        "missing-authority": "candidate_integrity_authority",
        "missing-digest": "candidate_archive_sha256",
    }
    if tamper == "authority":
        state["candidate_integrity_authority"]["runner_fingerprint"] = "f" * 64
    elif tamper == "schema-version":
        state["candidate_integrity_schema_version"] = "2"
    elif tamper == "missing-config":
        state.pop("config")
    elif tamper == "missing-all":
        for marker in marker_by_tamper.values():
            state.pop(marker)
    else:
        state.pop(marker_by_tamper[tamper])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    calls = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        calls["generate"] += 1
        pytest.fail("zero-candidate state-tampered resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        calls["evaluate"] += 1
        pytest.fail("zero-candidate state-tampered resume evaluated")

    with pytest.raises(EvolutionError, match=expected_error):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert calls == {"generate": 0, "evaluate": 0}


def test_modern_state_rejects_valid_active_and_best_substitution_before_callbacks(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    archive = CandidateArchive(tmp_path)
    valid_ids = [
        candidate.candidate_id
        for candidate in archive.records()
        if candidate.evaluation.validity == 1
    ]
    assert valid_ids == ["candidate-0001", "candidate-0002"]

    state_path = archive.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    active_id = state["active_ids"]["0"][0]
    best_id = state["best_candidate_id"]
    state["active_ids"] = {"0": [next(item for item in valid_ids if item != active_id)]}
    state["best_candidate_id"] = next(item for item in valid_ids if item != best_id)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("state-substituted resume generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("state-substituted resume evaluated")

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            generate=must_not_generate,
            evaluate=must_not_evaluate,
        )
    assert callbacks == {"generate": 0, "evaluate": 0}


@pytest.mark.parametrize(
    ("validities", "expected_active"),
    [
        ((1, 1), ["candidate-0002", "candidate-0001"]),
        ((0, 1), ["candidate-0002"]),
    ],
    ids=["multiple-valid", "invalid-excluded"],
)
def test_partial_initialization_cancellation_persists_reconstructable_projection(
    tmp_path: Path,
    validities: tuple[int, int],
    expected_active: list[str],
) -> None:
    cancellation_checks = 0
    reports = iter(
        [
            _report(0.1, valid=validities[0]),
            _report(0.9, valid=validities[1]),
        ]
    )

    def cancel_before_third_candidate() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 3

    config = _config(population_size=3, rng_seed=0)
    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
            lambda path, supplied: next(reports),
            config,
            cancelled=cancel_before_third_candidate,
        )
    ).run()

    archive = CandidateArchive(tmp_path)
    assert result.status == "cancelled"
    assert [candidate.candidate_id for candidate in archive.records()] == [
        "candidate-0001",
        "candidate-0002",
    ]
    state = archive.read_state()
    assert state["active_ids"] == {"0": expected_active}
    assert state["best_candidate_id"] == "candidate-0002"
    assert state["rng_seed"] == 0
    assert state["last_migration_iteration"] == 0
    assert state["stagnation"] == 0
    durable_before_resume = (
        archive.archive_path.read_bytes(),
        archive.state_path.read_bytes(),
    )

    resumed = _resume(
        tmp_path,
        config=config,
        generate=lambda request: pytest.fail("cancelled initialization resume generated"),
        evaluate=lambda path, supplied: pytest.fail(
            "cancelled initialization resume evaluated"
        ),
    )

    assert resumed.to_dict() == result.to_dict()
    assert durable_before_resume == (
        archive.archive_path.read_bytes(),
        archive.state_path.read_bytes(),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("rng_seed", False),
        ("rng_seed", 0.0),
        ("last_migration_iteration", False),
        ("last_migration_iteration", 0.0),
    ],
)
def test_modern_state_rejects_numeric_projection_type_substitution(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    config = _config(rng_seed=0)
    _run(tmp_path, config=config)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    state[field] = replacement
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("numeric state drift generated"),
            evaluate=lambda path, supplied: pytest.fail("numeric state drift evaluated"),
        )


@pytest.mark.parametrize("replacement", ["cancelled", "stagnated", "failed", "nonsense"])
def test_modern_state_rejects_contradictory_terminal_status(
    tmp_path: Path,
    replacement: str,
) -> None:
    config = _config()
    _run(tmp_path, config=config)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    assert state["status"] == "completed"
    state["status"] = replacement
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("status-drift resume generated"),
            evaluate=lambda path, supplied: pytest.fail("status-drift resume evaluated"),
        )


def test_modern_state_rejects_top_level_schema_drift(
    tmp_path: Path,
) -> None:
    config = _config()
    _run(tmp_path, config=config)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    state["schema_version"] = "2"
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("state-schema drift generated"),
            evaluate=lambda path, supplied: pytest.fail("state-schema drift evaluated"),
        )


def test_modern_state_cannot_strip_complete_outcome_binding_group(
    tmp_path: Path,
) -> None:
    config = _config()
    _run(tmp_path, config=config)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    for field in (
        "outcome_schema_version",
        "outcome_start_iteration",
        "outcome_watermark",
        "outcome_watermark_sha256",
        "outcome_archive_baseline_sha256",
    ):
        state.pop(field)
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive.offspring_outcomes_path.unlink()

    with pytest.raises(EvolutionError, match="^population_outcome_state_mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("stripped outcome binding generated"),
            evaluate=lambda path, supplied: pytest.fail("stripped outcome binding evaluated"),
        )


def test_modern_state_rejects_reconstructed_stagnation_drift_before_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(max_rounds=2, stagnation_rounds=5)
    original_write_state = CandidateArchive.write_state

    def persist_iteration_one_then_crash(self, payload):
        original_write_state(self, payload)
        if (
            payload.get("status") == "running"
            and payload.get("iteration") == 1
            and payload.get("outcome_watermark") == 1
        ):
            raise RuntimeError("simulated crash after iteration-one state")

    monkeypatch.setattr(CandidateArchive, "write_state", persist_iteration_one_then_crash)
    with pytest.raises(RuntimeError, match="simulated crash after iteration-one state"):
        _run(tmp_path, config=config)

    monkeypatch.setattr(CandidateArchive, "write_state", original_write_state)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    assert state["iteration"] == 1
    assert state["stagnation"] == 1
    state["stagnation"] = config.stagnation_rounds
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("stagnation-drift resume generated"),
            evaluate=lambda path, supplied: pytest.fail("stagnation-drift resume evaluated"),
        )


def test_modern_running_checkpoint_cannot_claim_early_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(max_rounds=2, stagnation_rounds=5)
    original_write_state = CandidateArchive.write_state

    def persist_iteration_one_then_crash(self, payload):
        original_write_state(self, payload)
        if (
            payload.get("status") == "running"
            and payload.get("iteration") == 1
            and payload.get("outcome_watermark") == 1
        ):
            raise RuntimeError("simulated crash after running checkpoint")

    monkeypatch.setattr(CandidateArchive, "write_state", persist_iteration_one_then_crash)
    with pytest.raises(RuntimeError, match="simulated crash after running checkpoint"):
        _run(tmp_path, config=config)

    monkeypatch.setattr(CandidateArchive, "write_state", original_write_state)
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    assert state["status"] == "running"
    assert state["iteration"] == 1
    state["status"] = "completed"
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("early-completed resume generated"),
            evaluate=lambda path, supplied: pytest.fail("early-completed resume evaluated"),
        )


def test_all_invalid_stagnation_failure_resumes_as_terminal(
    tmp_path: Path,
) -> None:
    config = _config(max_rounds=3, stagnation_rounds=1)
    result = _run(
        tmp_path,
        config=config,
        evaluate=lambda path, supplied: _report(1.0, valid=0),
    )
    assert result.status == "failed"
    assert result.iterations == 1
    assert result.best_candidate_id is None
    assert CandidateArchive(tmp_path).read_state()["stagnation"] == 1

    resumed = _resume(
        tmp_path,
        config=config,
        generate=lambda request: pytest.fail("invalid stagnation resume generated"),
        evaluate=lambda path, supplied: pytest.fail("invalid stagnation resume evaluated"),
    )

    assert resumed.to_dict() == result.to_dict()


def test_initial_failure_with_invalid_receipt_resumes_without_outcome_binding(
    tmp_path: Path,
) -> None:
    config = _config(population_size=2)
    evaluation_calls = 0

    def evaluate(path, supplied):
        nonlocal evaluation_calls
        del path, supplied
        evaluation_calls += 1
        if evaluation_calls == 1:
            return _report(1.0, valid=0)
        raise TimeoutError("private initialization timeout")

    result = _run(tmp_path, config=config, evaluate=evaluate)
    archive = CandidateArchive(tmp_path)
    assert result.status == "failed"
    assert result.error == "evaluator_timeout"
    assert result.iterations == 0
    assert [candidate.evaluation.validity for candidate in archive.records()] == [0]
    assert not archive.offspring_outcomes_path.exists()

    resumed = _resume(
        tmp_path,
        config=config,
        generate=lambda request: pytest.fail("initial failure resume generated"),
        evaluate=lambda path, supplied: pytest.fail("initial failure resume evaluated"),
    )

    assert resumed.to_dict() == result.to_dict()


def test_generator_only_initial_failure_checkpoint_keeps_retry_resume_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    original_write_state = CandidateArchive.write_state

    def fail_initial_generation(request):
        del request
        raise RuntimeError("initial generator failed")

    def persist_retry_checkpoint_then_crash(self, payload):
        original_write_state(self, payload)
        if (
            payload.get("status") == "running"
            and payload.get("iteration") == 0
            and payload.get("error") == "candidate_failed"
            and "outcome_schema_version" not in payload
        ):
            raise RuntimeError("simulated crash after generator retry checkpoint")

    monkeypatch.setattr(CandidateArchive, "write_state", persist_retry_checkpoint_then_crash)
    with pytest.raises(RuntimeError, match="generator retry checkpoint"):
        _run(
            tmp_path,
            config=config,
            generate=fail_initial_generation,
        )

    monkeypatch.setattr(CandidateArchive, "write_state", original_write_state)
    resumed = _resume(
        tmp_path,
        config=config,
        generate=lambda request: CandidateDraft("offspring = True\n"),
        evaluate=lambda path, supplied: _report(1.0),
    )

    assert resumed.status == "completed"
    assert resumed.iterations == 1
    assert [candidate.iteration for candidate in CandidateArchive(tmp_path).records()] == [0, 1]


def test_stagnated_terminal_state_cannot_claim_completion(
    tmp_path: Path,
) -> None:
    config = _config(max_rounds=1, stagnation_rounds=1)
    result = _run(tmp_path, config=config)
    assert result.status == "stagnated"
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    assert state["iteration"] == 1
    assert state["stagnation"] == 1
    state["status"] = "completed"
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("stagnated status drift generated"),
            evaluate=lambda path, supplied: pytest.fail("stagnated status drift evaluated"),
        )


@pytest.mark.parametrize("replacement", ["failed", "running"])
def test_cancelled_zero_candidate_state_cannot_claim_another_status(
    tmp_path: Path,
    replacement: str,
) -> None:
    config = _config()
    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: pytest.fail("pre-initialization cancellation generated"),
            lambda path, supplied: pytest.fail("pre-initialization cancellation evaluated"),
            config,
            cancelled=lambda: True,
        )
    ).run()
    assert result.status == "cancelled"
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    state["status"] = replacement
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("false initialization failure generated"),
            evaluate=lambda path, supplied: pytest.fail("false initialization failure evaluated"),
        )


def test_failed_initial_evaluator_state_cannot_claim_running(
    tmp_path: Path,
) -> None:
    config = _config()

    def timeout_initial_candidate(path, supplied):
        del path, supplied
        raise TimeoutError("private initialization timeout")

    result = _run(
        tmp_path,
        config=config,
        evaluate=timeout_initial_candidate,
    )
    assert result.status == "failed"
    assert result.error == "evaluator_timeout"
    archive = CandidateArchive(tmp_path)
    state = archive.read_state()
    state["status"] = "running"
    archive.state_path.write_text(
        json.dumps(state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError, match="^population state projection mismatch$"):
        _resume(
            tmp_path,
            config=config,
            generate=lambda request: pytest.fail("false running state generated"),
            evaluate=lambda path, supplied: pytest.fail("false running state evaluated"),
        )


def test_legacy_ordinary_archive_is_readable_but_active_resume_is_rejected(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    root = tmp_path / "evolution"
    archive_path = root / "archive.jsonl"
    records = [json.loads(line) for line in archive_path.read_text().splitlines()]
    # Remove every additive Feature 087 field from both legacy record locations.
    for record in records:
        for key in ("source_sha256", "receipt_sha256", "integrity"):
            record.pop(key, None)
    archive_path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    for candidate_id in ("candidate-0001", "candidate-0002"):
        record_path = root / "candidates" / candidate_id / "record.json"
        record = json.loads(record_path.read_text())
        for key in ("source_sha256", "receipt_sha256", "integrity"):
            record.pop(key, None)
        record_path.write_text(json.dumps(record, sort_keys=True) + "\n")
        (record_path.parent / "receipt.json").unlink()
    state_path = root / "state.json"
    state = json.loads(state_path.read_text())
    for key in (
        "candidate_integrity_schema_version",
        "candidate_integrity_authority",
        "candidate_archive_sha256",
    ):
        state.pop(key, None)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n")

    assert len(CandidateArchive(tmp_path).records()) == 2
    with pytest.raises(EvolutionError, match=LEGACY_CANDIDATE_INTEGRITY_ERROR):
        _resume(
            tmp_path,
            generate=lambda request: pytest.fail("legacy resume generated"),
            evaluate=lambda path, contract: pytest.fail("legacy resume evaluated"),
        )


def test_candidate_receipt_round_trip_rejects_unknown_fields_and_recomputed_digest(
    tmp_path: Path,
) -> None:
    _run(tmp_path)
    receipt_path = tmp_path / "evolution" / "candidates" / "candidate-0001" / "receipt.json"
    payload = json.loads(receipt_path.read_text())
    receipt = CandidateReceipt.from_dict(payload)
    assert CandidateReceipt.from_dict(receipt.to_dict()) == receipt
    assert receipt.to_dict() == payload
    unknown = dict(payload)
    unknown["unexpected"] = True
    with pytest.raises(EvolutionError, match="ordinary_candidate_receipt_invalid"):
        CandidateReceipt.from_dict(unknown)
    altered = dict(payload)
    altered["combined_score"] = altered["combined_score"] + 0.1
    with pytest.raises(EvolutionError, match="ordinary_candidate_receipt_invalid"):
        CandidateReceipt.from_dict(altered)


def test_candidate_receipt_from_report_redacts_error_prose_and_binds_all_authorities() -> None:
    report = EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "local evaluator:v1",
            "validity": 0,
            "quality": None,
            "combined_score": 0,
            "detailed_scores": {},
            "error_info": [
                {
                    "code": "constraint violated",
                    "message": "provider returned a private evaluator explanation",
                }
            ],
        }
    )
    receipt = CandidateReceipt.from_report(
        report,
        candidate_id="candidate-0001",
        source_sha256="a" * 64,
        contract_sha256="b" * 64,
        evaluator_kind="callback",
        evaluator_fingerprint=EVALUATOR_SHA,
        dependency_sha256=DEPENDENCY_SHA,
        environment_sha256=ENVIRONMENT_SHA,
        runner_fingerprint=RUNNER_SHA,
        generator_fingerprint=GENERATOR_SHA,
        parent_id=None,
        generation=0,
        iteration=0,
        island_id=0,
    )
    assert receipt.evaluator_id == "local evaluator:v1"
    assert receipt.error_info == (
        {
            "code": "constraint violated",
            "message": "local evaluator reported an error",
        },
    )
    assert "private evaluator explanation" not in json.dumps(receipt.to_dict())
    assert receipt.receipt_sha256 == _canonical_digest(receipt.canonical_payload())


def test_credential_like_evaluator_kind_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    credential_kind = "sk-abcdefghijkl"
    with pytest.raises(ValueError, match="evaluator_kind must be a safe identifier"):
        _config(evaluator_kind=credential_kind)
    with pytest.raises(ValueError, match="evaluator_kind must be a safe identifier"):
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: CandidateDraft("candidate = 1\n"),
            lambda path, supplied: _report(0.5),
            _config(evaluator_kind=None),
            evaluator_kind=credential_kind,
        )

    authority = _authority().to_dict()
    authority["evaluator_kind"] = credential_kind
    with pytest.raises(EvolutionError, match="^ordinary_candidate_integrity_invalid$"):
        CandidateIntegrityAuthority.from_dict(authority)

    receipt = CandidateReceipt.from_report(
        _report(0.5),
        candidate_id="candidate-0001",
        source_sha256="a" * 64,
        contract_sha256="b" * 64,
        evaluator_kind="callback",
        evaluator_fingerprint=EVALUATOR_SHA,
        dependency_sha256=DEPENDENCY_SHA,
        environment_sha256=ENVIRONMENT_SHA,
        runner_fingerprint=RUNNER_SHA,
        generator_fingerprint=GENERATOR_SHA,
        parent_id=None,
        generation=0,
        iteration=0,
        island_id=0,
    ).to_dict()
    receipt["evaluator_kind"] = credential_kind
    receipt["receipt_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    with pytest.raises(EvolutionError, match="^ordinary_candidate_receipt_invalid$"):
        CandidateReceipt.from_dict(receipt)

    assert not (tmp_path / "evolution").exists()


@pytest.mark.parametrize(
    ("context_field", "context_value"),
    [
        ("evaluator_kind", "other-callback"),
        ("dependency_sha256", "a" * 64),
        ("environment_sha256", "b" * 64),
    ],
)
def test_context_and_config_authority_conflict_is_rejected_before_callbacks(
    tmp_path: Path,
    context_field: str,
    context_value: str,
) -> None:
    callbacks = {"generate": 0, "evaluate": 0}

    def must_not_generate(request):
        del request
        callbacks["generate"] += 1
        pytest.fail("authority-conflicted strategy generated")

    def must_not_evaluate(path, contract):
        del path, contract
        callbacks["evaluate"] += 1
        pytest.fail("authority-conflicted strategy evaluated")

    with pytest.raises(EvolutionError, match="^ordinary_candidate_integrity_invalid$"):
        PopulationStrategy(
            EvolutionContext(
                _contract(),
                tmp_path,
                must_not_generate,
                must_not_evaluate,
                _config(),
                **{context_field: context_value},
            )
        )
    assert callbacks == {"generate": 0, "evaluate": 0}
    assert not (tmp_path / "evolution").exists()


def test_controller_indexes_ordinary_sidecars_idempotently(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    contract = _contract()
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    config = _config()

    settled, result = controller.run_evolution(
        run.id,
        contract,
        lambda request: CandidateDraft(f"iteration = {request.iteration}\n"),
        lambda path, supplied: _report(0.5),
        config,
    )
    assert settled.status.value == "succeeded"
    assert result.best_candidate_id in {"candidate-0001", "candidate-0002"}
    first = controller.store.list_artifacts(run.id)
    sidecars = [
        item
        for item in first
        if item["kind"] in {"evolution_candidate_record", "evolution_candidate_receipt"}
    ]
    assert len(sidecars) == 4
    controller.run_evolution(
        run.id,
        contract,
        lambda request: pytest.fail("terminal resume generated"),
        lambda path, supplied: pytest.fail("terminal resume evaluated"),
        config,
    )
    second = controller.store.list_artifacts(run.id)
    sidecars_again = [
        item
        for item in second
        if item["kind"] in {"evolution_candidate_record", "evolution_candidate_receipt"}
    ]
    assert sidecars_again == sidecars
