from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

import famou.shinka_handoff as shinka_module
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.producer_handoff import (
    MAX_PRODUCER_BUDGET_FIELDS,
    ProducerResultEnvelope,
    admit_producer_result,
)
from famou.shinka_handoff import (
    SHINKA_DATABASE_CODE_MISMATCH,
    SHINKA_DATABASE_MISSING,
    SHINKA_DATABASE_WAL_UNSUPPORTED,
    SHINKA_EXPORT_CLEANUP_FAILED,
    SHINKA_EXPORT_COMMIT_UNKNOWN,
    SHINKA_EXPORT_PATH_UNSAFE,
    SHINKA_EXPORT_ROOT_UNSAFE,
    SHINKA_FINGERPRINT_REQUIRED,
    SHINKA_LINEAGE_CYCLE,
    SHINKA_LINEAGE_MISSING,
    SHINKA_NO_CORRECT_PROGRAMS,
    SHINKA_PROGRAM_NOT_FOUND,
    SHINKA_PROGRAM_SELECTION_INVALID,
    SHINKA_SOURCE_MISSING,
    SHINKA_SOURCE_PATH_UNSAFE,
    SHINKA_TOP_K_INVALID,
    ShinkaHandoffError,
    export_shinka_result,
)

CONTRACT_SHA = "c" * 64
PRODUCER_SHA = "b" * 64
EVALUATOR_SHA = "e" * 64


def _admission_contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "shinka-admission-fixture",
            "problem_type": "routing",
            "statement": "Find a deterministic route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every item is served."],
            "deliverables": ["route source"],
            "evolution": {"strategy": "population", "max_rounds": 2, "stagnation_rounds": 1},
        }
    )


def _admission_report(score: float, *, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "shinka-local-exact",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
            "error_info": [] if valid else [{"code": "invalid", "message": "fixture invalid"}],
        }
    )


def _create_db(root: Path, *, name: str = "programs.sqlite") -> sqlite3.Connection:
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / name)
    connection.execute(
        """
        CREATE TABLE programs (
            id TEXT,
            code TEXT,
            language TEXT,
            parent_id TEXT,
            generation INTEGER,
            combined_score REAL,
            correct BOOLEAN
        )
        """
    )
    return connection


def _insert(
    connection: sqlite3.Connection,
    program_id: str,
    code: str,
    *,
    parent_id: str | None = None,
    generation: int = 0,
    score: float | None = 0.0,
    correct: int = 1,
) -> None:
    connection.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (program_id, code, "python", parent_id, generation, score, correct),
    )


def _write_generation(root: Path, generation: int, code: str) -> None:
    directory = root / f"gen_{generation}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "main.py").write_text(code, encoding="utf-8")


def _export(root: Path, export: Path, *, top_k: int | None = 1):
    return export_shinka_result(
        root,
        export,
        contract_sha256=CONTRACT_SHA,
        producer_fingerprint=PRODUCER_SHA,
        top_k=top_k,
        producer_run_id="run-1",
    )


def test_exports_explicit_top_k_and_global_parent_lineage(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    first_code = "answer = 1\n"
    second_code = "answer = 2\n"
    _insert(connection, "root", first_code, score=1.0)
    _insert(connection, "child", second_code, parent_id="root", generation=1, score=2.0)
    _insert(connection, "bad", "answer = 999\n", generation=2, score=999.0, correct=0)
    connection.commit()
    connection.close()
    _write_generation(root, 0, first_code)
    _write_generation(root, 1, second_code)

    envelope = _export(tmp_path / "run", tmp_path / "export", top_k=2)

    assert envelope.status == "completed"
    assert [material.path for material in envelope.materials] == [
        "candidates/000-child/main.py",
        "candidates/001-root/main.py",
    ]
    assert [material.lineage for material in envelope.materials] == [("root",), ()]
    assert (tmp_path / "export" / "candidates/000-child/main.py").read_text() == second_code
    assert (tmp_path / "export" / "candidates/001-root/main.py").read_text() == first_code
    serialized = json.dumps(envelope.to_dict(), sort_keys=True)
    assert "999.0" not in serialized
    assert (tmp_path / "export" / "producer-result.json").exists()
    parsed = ProducerResultEnvelope.from_dict(
        json.loads((tmp_path / "export" / "producer-result.json").read_text())
    )
    assert parsed == envelope


def test_falls_back_to_legacy_database_and_best_source_only_when_generation_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root, name="evolution_db.sqlite")
    code = "answer = 7\n"
    _insert(connection, "best-id", code, generation=7, score=7.0)
    connection.commit()
    connection.close()
    best = root / "best"
    best.mkdir()
    (best / "main.py").write_text(code, encoding="utf-8")

    envelope = _export(root, tmp_path / "export")

    assert envelope.materials[0].sha256
    assert (tmp_path / "export" / envelope.materials[0].path).read_text() == code


def test_omitted_top_k_selects_one_convenience_program(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "first", "answer = 1\n", score=1.0)
    _insert(connection, "second", "answer = 2\n", generation=1, score=2.0)
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    _write_generation(root, 1, "answer = 2\n")

    envelope = export_shinka_result(
        root,
        tmp_path / "export",
        contract_sha256=CONTRACT_SHA,
        producer_fingerprint=PRODUCER_SHA,
    )

    assert [item.path for item in envelope.materials] == ["candidates/000-second/main.py"]


def test_explicit_program_ids_must_omit_top_k(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")

    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            root,
            tmp_path / "export",
            contract_sha256=CONTRACT_SHA,
            producer_fingerprint=PRODUCER_SHA,
            top_k=1,
            program_ids=("program",),
        )
    assert caught.value.code == SHINKA_PROGRAM_SELECTION_INVALID


def test_generation_source_is_authoritative_when_best_is_stale(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    code = "answer = 3\n"
    _insert(connection, "program", code, generation=2, score=3.0)
    connection.commit()
    connection.close()
    _write_generation(root, 2, code)
    best = root / "best"
    best.mkdir()
    (best / "main.py").write_text("answer = stale\n", encoding="utf-8")

    envelope = _export(root, tmp_path / "export")
    assert (tmp_path / "export" / envelope.materials[0].path).read_text() == code


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        ("missing_source", SHINKA_SOURCE_MISSING),
        ("mismatch", SHINKA_DATABASE_CODE_MISMATCH),
        ("symlink", SHINKA_SOURCE_PATH_UNSAFE),
    ],
)
def test_source_integrity_fail_closed(tmp_path: Path, mutator: str, expected: str) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    code = "answer = 4\n"
    _insert(connection, "program", code, generation=3)
    connection.commit()
    connection.close()
    generation = root / "gen_3"
    generation.mkdir()
    if mutator == "mismatch":
        (generation / "main.py").write_text("answer = changed\n", encoding="utf-8")
    elif mutator == "symlink":
        outside = tmp_path / "outside.py"
        outside.write_text(code, encoding="utf-8")
        (generation / "main.py").symlink_to(outside)

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == expected


@pytest.mark.parametrize("kind", ["missing", "cycle"])
def test_parent_lineage_rejects_missing_rows_and_cycles(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    code = "answer = 5\n"
    parent = "missing-parent" if kind == "missing" else "program"
    _insert(connection, "program", code, parent_id=parent, generation=1)
    if kind == "cycle":
        _insert(connection, "program-parent", "answer = 6\n", parent_id="program")
        connection.execute("UPDATE programs SET parent_id = 'program-parent' WHERE id = 'program'")
        connection.execute("UPDATE programs SET parent_id = 'program' WHERE id = 'program-parent'")
    connection.commit()
    connection.close()
    _write_generation(root, 1, code)

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == (
        SHINKA_LINEAGE_MISSING if kind == "missing" else SHINKA_LINEAGE_CYCLE
    )


def test_fixed_bounds_and_root_database_requirements(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == SHINKA_DATABASE_MISSING

    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export", top_k=0)
    assert caught.value.code == SHINKA_TOP_K_INVALID

    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            root,
            tmp_path / "export2",
            contract_sha256=CONTRACT_SHA,
            producer_fingerprint="short",
        )
    assert caught.value.code == SHINKA_FINGERPRINT_REQUIRED


def test_no_correct_programs_is_not_reinterpreted_as_success(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "bad", "answer = 0\n", correct=0)
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 0\n")

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == SHINKA_NO_CORRECT_PROGRAMS


def test_explicit_program_ids_bypass_native_correctness_and_preserve_order(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    first = "answer = 11\n"
    second = "answer = 12\n"
    _insert(connection, "incorrect", first, generation=1, score=100.0, correct=0)
    _insert(connection, "correct", second, generation=2, score=1.0, correct=1)
    connection.commit()
    connection.close()
    _write_generation(root, 1, first)
    _write_generation(root, 2, second)

    envelope = export_shinka_result(
        root,
        tmp_path / "export",
        contract_sha256=CONTRACT_SHA,
        producer_fingerprint=PRODUCER_SHA,
        top_k=None,
        program_ids=("incorrect", "correct"),
    )

    assert [item.lineage for item in envelope.materials] == [(), ()]
    assert [item.external_evidence["present"] for item in envelope.materials] == [True, True]
    assert (tmp_path / "export" / envelope.materials[0].path).read_text() == first


def test_explicit_program_ids_require_existing_ids(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")

    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            root,
            tmp_path / "export",
            contract_sha256=CONTRACT_SHA,
            producer_fingerprint=PRODUCER_SHA,
            top_k=None,
            program_ids=("missing",),
        )
    assert caught.value.code == SHINKA_PROGRAM_NOT_FOUND


def test_export_root_cannot_overlap_results_root(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, root / "nested-export")
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE


def test_export_root_symlinked_ancestor_cannot_alias_results_root(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, alias / "nested")
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE


def test_export_root_rejects_unrelated_symlinked_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, alias / "nested")
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE
    assert not (outside / "nested").exists()


def test_envelope_path_cannot_replace_a_material(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")

    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            root,
            tmp_path / "export",
            contract_sha256=CONTRACT_SHA,
            producer_fingerprint=PRODUCER_SHA,
            envelope_path="candidates/000-program/main.py",
        )
    assert caught.value.code == SHINKA_EXPORT_PATH_UNSAFE


def test_exporter_never_overwrites_an_existing_output_file(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    export = tmp_path / "export"
    export.mkdir()
    target = export / "producer-result.json"
    target.write_text("caller-owned\n", encoding="utf-8")

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, export)
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE
    assert target.read_text(encoding="utf-8") == "caller-owned\n"


def test_exporter_rejects_an_existing_empty_output_root(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    export = tmp_path / "export"
    export.mkdir()

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, export)
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE
    assert export.is_dir() and not any(export.iterdir())


def test_failed_staging_write_leaves_no_final_tree_or_staging_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "first", "answer = 1\n", score=2.0)
    _insert(connection, "second", "answer = 2\n", generation=1, score=1.0)
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    _write_generation(root, 1, "answer = 2\n")
    export = tmp_path / "export"
    original = shinka_module._write_export_file
    calls = 0

    def fail_on_second(destination: Path, relative: str, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original(destination, relative, content)

    monkeypatch.setattr(shinka_module, "_write_export_file", fail_on_second)
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, export, top_k=2)
    assert caught.value.code == "shinka_export_write_failed"
    assert not export.exists()
    assert not [item for item in tmp_path.iterdir() if item.name.startswith(".export.")]


def test_cleanup_failure_has_a_fixed_code_and_does_not_claim_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    original_write = shinka_module._write_export_file
    original_remove = shinka_module.shutil.rmtree

    def fail_write(destination: Path, relative: str, content: bytes) -> None:
        raise OSError("injected write failure")

    def fail_remove(path: Path) -> None:
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(shinka_module, "_write_export_file", fail_write)
    monkeypatch.setattr(shinka_module.shutil, "rmtree", fail_remove)
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == SHINKA_EXPORT_CLEANUP_FAILED
    monkeypatch.setattr(shinka_module, "_write_export_file", original_write)
    monkeypatch.setattr(shinka_module.shutil, "rmtree", original_remove)
    staging = [item for item in tmp_path.iterdir() if item.name.startswith(".export.")]
    assert len(staging) == 1
    original_remove(staging[0])


def test_parent_fsync_failure_reports_commit_unknown_and_keeps_published_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    original_fsync = shinka_module._fsync_directory
    calls = 0

    def fail_parent(path: Path) -> None:
        nonlocal calls
        calls += 1
        if path == tmp_path:
            raise ShinkaHandoffError("injected_parent_fsync_failure")
        original_fsync(path)

    monkeypatch.setattr(shinka_module, "_fsync_directory", fail_parent)
    export = tmp_path / "export"
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, export)
    assert caught.value.code == SHINKA_EXPORT_COMMIT_UNKNOWN
    assert (export / "producer-result.json").is_file()


def test_commit_race_does_not_replace_a_new_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    export = tmp_path / "export"
    original_rename = shinka_module._rename_noreplace

    def race(staging: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "caller-owned").write_text("keep\n", encoding="utf-8")
        original_rename(staging, destination)

    monkeypatch.setattr(shinka_module, "_rename_noreplace", race)
    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, export)
    assert caught.value.code == SHINKA_EXPORT_ROOT_UNSAFE
    assert (export / "caller-owned").read_text(encoding="utf-8") == "keep\n"
    assert not [item for item in tmp_path.iterdir() if item.name.startswith(".export.")]


def test_wal_database_is_rejected_without_creating_or_mutating_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    _write_generation(root, 0, "answer = 1\n")
    sidecars = {
        path.name: path.read_bytes()
        for path in root.glob("programs.sqlite-*")
        if path.is_file()
    }

    try:
        with pytest.raises(ShinkaHandoffError) as caught:
            _export(root, tmp_path / "export")
        assert caught.value.code == SHINKA_DATABASE_WAL_UNSUPPORTED
        assert {
            path.name: path.read_bytes()
            for path in root.glob("programs.sqlite-*")
            if path.is_file()
        } == sidecars
    finally:
        connection.close()


def test_rollback_journal_sidecar_is_rejected_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")
    journal = root / "programs.sqlite-journal"
    journal.write_bytes(b"journal-bytes")

    with pytest.raises(ShinkaHandoffError) as caught:
        _export(root, tmp_path / "export")
    assert caught.value.code == SHINKA_DATABASE_WAL_UNSUPPORTED
    assert journal.read_bytes() == b"journal-bytes"


def test_shinka_export_converges_on_generic_local_admission(tmp_path: Path) -> None:
    """SQLite material and a generic envelope share Lunar's exact-evaluator authority."""

    results_root = tmp_path / "run"
    connection = _create_db(results_root)
    parent_code = "answer = 1\n"
    good_code = "answer = 2\n"
    bad_code = "answer = 3\n"
    _insert(connection, "root", parent_code, generation=0, score=1.0)
    _insert(
        connection,
        "good",
        good_code,
        parent_id="root",
        generation=1,
        score=9999.0,
        correct=1,
    )
    _insert(
        connection,
        "bad",
        bad_code,
        parent_id="root",
        generation=2,
        score=10000.0,
        correct=0,
    )
    connection.execute("ALTER TABLE programs ADD COLUMN feedback TEXT")
    connection.execute("UPDATE programs SET feedback = 'private producer prose'")
    connection.commit()
    connection.close()
    _write_generation(results_root, 0, parent_code)
    _write_generation(results_root, 1, good_code)
    _write_generation(results_root, 2, bad_code)

    contract = _admission_contract()
    export_root = tmp_path / "export"
    export_shinka_result(
        results_root,
        export_root,
        contract_sha256=contract.digest(),
        producer_fingerprint=PRODUCER_SHA,
        producer_run_id="sqlite-fixture",
        top_k=None,
        program_ids=("good", "bad"),
    )
    exported_envelope = (export_root / "producer-result.json").read_text(encoding="utf-8")
    assert "private producer prose" not in exported_envelope
    assert "9999.0" not in exported_envelope
    assert "10000.0" not in exported_envelope

    evaluated: list[str] = []

    def evaluator(path: Path, supplied: AlgorithmProblemContract) -> EvaluationReport:
        assert supplied == contract
        source = path.read_text(encoding="utf-8")
        evaluated.append(source)
        if source == good_code:
            return _admission_report(0.42)
        return _admission_report(999999.0, valid=0)

    result = admit_producer_result(
        export_root,
        contract,
        evaluator,
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_fingerprint=PRODUCER_SHA,
        producer_id="shinka",
        staging_root=tmp_path / "staging",
    )

    assert evaluated == [good_code, bad_code]
    assert len(result.admitted) == 1
    assert result.admitted[0].evaluation.combined_score == 0.42
    assert result.admitted[0].draft.metadata["seed_handoff"]["lineage"] == ["root"]
    assert result.rejected[0].code == "local_evaluation_invalid"
    external_evidence = result.admitted[0].provenance.external_evidence
    assert set(external_evidence) == {"present", "score_present", "payload_sha256"}
    assert external_evidence["present"] is True
    assert external_evidence["score_present"] is True
    assert len(external_evidence["payload_sha256"]) == 64
    canonical_metadata = json.dumps(result.admitted[0].draft.metadata, sort_keys=True)
    assert "9999.0" not in canonical_metadata
    assert "10000.0" not in canonical_metadata


def test_shinka_budget_mapping_is_bounded_before_export_creation(tmp_path: Path) -> None:
    root = tmp_path / "run"
    connection = _create_db(root)
    _insert(connection, "program", "answer = 1\n")
    connection.commit()
    connection.close()
    _write_generation(root, 0, "answer = 1\n")

    class OversizedMapping(Mapping[str, int]):
        def __iter__(self):
            return iter(f"field_{index}" for index in range(MAX_PRODUCER_BUDGET_FIELDS + 1))

        def __len__(self) -> int:
            return MAX_PRODUCER_BUDGET_FIELDS + 1

        def __getitem__(self, key: str) -> int:
            return 1

    export = tmp_path / "export"
    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            root,
            export,
            contract_sha256=CONTRACT_SHA,
            producer_fingerprint=PRODUCER_SHA,
            budget=OversizedMapping(),
        )
    assert caught.value.code == "shinka_budget_invalid"
    assert not export.exists()
