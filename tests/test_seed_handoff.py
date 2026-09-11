from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.seed_handoff import (
    CONTRACT_MISMATCH,
    DEPENDENCY_MISMATCH,
    DUPLICATE_IDENTITY,
    DUPLICATE_SOURCE,
    EMPTY_MANIFEST,
    ENVIRONMENT_MISMATCH,
    EVALUATOR_FAILED,
    EVALUATOR_MISMATCH,
    EXTERNAL_REQUIRES_EXACT_HARNESS,
    EXTERNAL_SCORE_ONLY,
    IDENTITY_COLLISION,
    IDENTITY_MISMATCH,
    INVALID_EVALUATION_REPORT,
    LOCAL_EVALUATION_INVALID,
    LOCAL_SCORE_UNAVAILABLE,
    MANIFEST_INVALID,
    MANIFEST_ROOT_REQUIRED,
    METADATA_TOO_LARGE,
    NO_USABLE_SEEDS,
    SOURCE_CHANGED,
    SOURCE_DIGEST_MISMATCH,
    SOURCE_EMPTY,
    SOURCE_ENCODING_INVALID,
    SOURCE_MISSING,
    SOURCE_NOT_REGULAR,
    SOURCE_TOO_LARGE,
    SOURCE_UNSAFE,
    STAGED_SOURCE_CHANGED,
    TOO_MANY_SEEDS,
    UNKNOWN_FIELD,
    EvaluatorReceipt,
    SeedAdmissionError,
    SeedManifest,
    admit_seed_manifest,
    compute_handoff_fingerprint,
    compute_seed_identity,
    parse_seed_manifest,
)

EVALUATOR_SHA = "a" * 64
DEPENDENCY_SHA = "b" * 64
ENVIRONMENT_SHA = "c" * 64
PRODUCER_SHA = "d" * 64


def _contract(problem_id: str = "seed-fixture") -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": problem_id,
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}
            ],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {
                "strategy": "population",
                "max_rounds": 2,
                "stagnation_rounds": 1,
            },
        }
    )


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _report(score: float = 1.25, *, validity: int = 1) -> dict[str, object]:
    return {
        "schema_version": "1",
        "evaluator_id": "local-fixture",
        "validity": validity,
        "quality": score if validity else None,
        "combined_score": score if validity else 0,
        "detailed_scores": {
            "route quality": {"value": score, "direction": "maximize"}
        },
        "error_info": (
            []
            if validity
            else [{"code": "invalid-route", "message": "fixture invalid detail"}]
        ),
    }


def _record(
    source_path: str,
    source_sha256: str,
    *,
    origin_kind: str = "local",
    producer_run_id: str | None = None,
    lineage: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    external_evidence: dict[str, object] | None = None,
    identity: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "source_path": source_path,
        "source_sha256": source_sha256,
        "lineage": lineage or [],
        "provenance": {
            "origin_kind": origin_kind,
            "producer_id": "openevolve" if origin_kind == "external" else "operator",
            "producer_fingerprint": PRODUCER_SHA,
            "producer_run_id": producer_run_id,
            "material_refs": ["material-001"],
            "external_evidence": external_evidence or {},
        },
        "metadata": metadata or {},
    }
    if identity is not None:
        record["identity"] = identity
    return record


def _manifest(
    contract: AlgorithmProblemContract,
    seeds: list[dict[str, object]],
    *,
    evaluator_kind: str = "exact_harness",
    evaluator_sha: str = EVALUATOR_SHA,
    dependency_sha: str = DEPENDENCY_SHA,
    environment_sha: str = ENVIRONMENT_SHA,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "contract_sha256": contract.digest(),
        "evaluator": {"kind": evaluator_kind, "fingerprint": evaluator_sha},
        "dependency_sha256": dependency_sha,
        "environment_sha256": environment_sha,
        "seeds": seeds,
    }


def _write_manifest(root: Path, value: object) -> Path:
    path = root / "seed-manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _admit(
    manifest: object,
    contract: AlgorithmProblemContract,
    evaluator,
    *,
    manifest_root: Path | None = None,
    staging_root: Path | None = None,
    evaluator_kind: str = "exact_harness",
    evaluator_sha: str = EVALUATOR_SHA,
    dependency_sha: str = DEPENDENCY_SHA,
    environment_sha: str = ENVIRONMENT_SHA,
    num_islands: int = 1,
):
    return admit_seed_manifest(
        manifest,
        contract,
        evaluator,
        evaluator_kind=evaluator_kind,
        evaluator_fingerprint=evaluator_sha,
        dependency_sha256=dependency_sha,
        environment_sha256=environment_sha,
        manifest_root=manifest_root,
        staging_root=staging_root,
        num_islands=num_islands,
    )


def _rejection(
    root: Path,
    contract: AlgorithmProblemContract,
    record: dict[str, object],
    evaluator,
    **kwargs,
) -> str:
    path = _write_manifest(root, _manifest(contract, [record], **kwargs.pop("manifest", {})))
    with pytest.raises(SeedAdmissionError) as caught:
        _admit(path, contract, evaluator, **kwargs)
    assert caught.value.code == NO_USABLE_SEEDS
    assert caught.value.result is not None
    assert len(caught.value.result.rejected) == 1
    return caught.value.result.rejected[0].code


def test_valid_seed_is_locally_re_evaluated_with_stable_population_fields(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "seeds" / "candidate.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    manifest = _manifest(
        contract,
        [
            _record(
                "seeds/candidate.py",
                _sha(source.read_bytes()),
                origin_kind="external",
                producer_run_id="remote-run-42",
                lineage=["parent-001"],
                metadata={"label": "warm start"},
                external_evidence={"external_score": 999.0},
            )
        ],
    )
    manifest_path = _write_manifest(tmp_path, manifest)
    seen: list[Path] = []

    def evaluator(path: Path, received_contract: AlgorithmProblemContract):
        assert received_contract is contract
        assert path != source
        assert path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
        assert oct(path.parent.parent.stat().st_mode & 0o777) == "0o700"
        seen.append(path)
        return _report(3.5)

    result = _admit(
        manifest_path,
        contract,
        evaluator,
        staging_root=tmp_path / "private-staging",
        num_islands=2,
    )

    assert len(seen) == 1
    assert not seen[0].exists()
    assert result.rejected == ()
    admitted = result.admitted[0]
    parsed = SeedManifest.from_path(manifest_path)
    assert admitted.candidate_id == compute_seed_identity(parsed.seeds[0], parsed)
    assert admitted.candidate_id.startswith("seed-")
    assert admitted.generation == admitted.iteration == 0
    assert admitted.parent_id is None
    assert admitted.strategy == "population"
    assert admitted.island_id == 0
    assert admitted.evaluation.combined_score == 3.5
    assert admitted.draft.source == "answer = 42\n"
    handoff = admitted.draft.metadata["seed_handoff"]
    assert handoff["receipt_sha256"] == admitted.receipt.receipt_sha256
    assert handoff["provenance"]["producer_id"] == "openevolve"
    assert "external_score" not in json.dumps(handoff)
    assert admitted.provenance.external_evidence == {
        "present": True,
        "score_present": True,
        "payload_sha256": admitted.provenance.external_evidence["payload_sha256"],
    }
    assert len(admitted.provenance.external_evidence["payload_sha256"]) == 64
    assert admitted.draft.metadata["seed_metadata"] == {
        "present": True,
        "score_present": False,
        "payload_sha256": admitted.draft.metadata["seed_metadata"]["payload_sha256"],
    }
    assert "warm start" not in json.dumps(admitted.draft.metadata)


def test_identity_and_receipt_are_byte_stable_and_receipt_digest_is_recomputable(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("value = 7\n", encoding="utf-8")
    path = _write_manifest(
        tmp_path,
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
    )

    first = _admit(path, contract, lambda *_: _report(2.0)).admitted[0]
    second = _admit(path, contract, lambda *_: _report(2.0)).admitted[0]

    assert first.candidate_id == second.candidate_id
    assert first.receipt.receipt_sha256 == second.receipt.receipt_sha256
    assert first.handoff_sha256 == second.handoff_sha256
    payload = first.receipt.to_dict()
    digest = payload.pop("receipt_sha256")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == digest
    assert EvaluatorReceipt.from_dict(first.receipt.to_dict()) == first.receipt


def test_producer_run_id_changes_handoff_fingerprint_but_not_candidate_identity(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("value = 1\n", encoding="utf-8")
    digest = _sha(source.read_bytes())
    first = _manifest(
        contract,
        [
            _record(
                "candidate.py",
                digest,
                origin_kind="external",
                producer_run_id="run-a",
            )
        ],
    )
    second = deepcopy(first)
    second["seeds"][0]["provenance"]["producer_run_id"] = "run-b"

    admitted_a = _admit(first, contract, lambda *_: _report(), manifest_root=tmp_path).admitted[0]
    admitted_b = _admit(second, contract, lambda *_: _report(), manifest_root=tmp_path).admitted[0]

    assert admitted_a.candidate_id == admitted_b.candidate_id
    assert admitted_a.receipt.receipt_sha256 == admitted_b.receipt.receipt_sha256
    assert admitted_a.handoff_sha256 != admitted_b.handoff_sha256
    assert admitted_b.handoff_sha256 == compute_handoff_fingerprint(
        admitted_b.candidate_id,
        admitted_b.provenance,
    )


def test_mixed_batch_returns_only_admitted_subset_after_all_records_are_adjudicated(
    tmp_path: Path,
) -> None:
    contract = _contract()
    valid = tmp_path / "valid.py"
    invalid = tmp_path / "invalid.py"
    valid.write_text("status = 'valid'\n", encoding="utf-8")
    invalid.write_text("status = 'invalid'\n", encoding="utf-8")
    manifest = _manifest(
        contract,
        [
            _record("valid.py", _sha(valid.read_bytes())),
            _record("missing.py", "1" * 64),
            _record("invalid.py", _sha(invalid.read_bytes())),
        ],
    )
    calls: list[str] = []

    def evaluator(path: Path, _contract: AlgorithmProblemContract):
        source = path.read_text(encoding="utf-8")
        calls.append(source)
        return _report(validity=0) if "invalid" in source else _report()

    result = _admit(manifest, contract, evaluator, manifest_root=tmp_path)

    assert len(result.admitted) == 1
    assert [item.code for item in result.rejected] == [SOURCE_MISSING, LOCAL_EVALUATION_INVALID]
    assert len(calls) == 2
    assert result.admitted[0].draft.source == "status = 'valid'\n"


def test_all_invalid_fails_closed_with_bounded_adjudication_result(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "invalid.py"
    source.write_text("invalid = True\n", encoding="utf-8")
    manifest = _manifest(
        contract,
        [
            _record("missing.py", "1" * 64),
            _record("invalid.py", _sha(source.read_bytes())),
        ],
    )
    calls = 0

    def evaluator(*_args):
        nonlocal calls
        calls += 1
        return _report(validity=0)

    with pytest.raises(SeedAdmissionError) as caught:
        _admit(manifest, contract, evaluator, manifest_root=tmp_path)

    assert caught.value.code == NO_USABLE_SEEDS
    assert caught.value.result is not None
    assert caught.value.result.admitted == ()
    assert [item.code for item in caught.value.result.rejected] == [
        SOURCE_MISSING,
        LOCAL_EVALUATION_INVALID,
    ]
    assert calls == 1
    assert str(caught.value) == NO_USABLE_SEEDS


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(extra=True), UNKNOWN_FIELD),
        (lambda value: value["evaluator"].update(extra=True), UNKNOWN_FIELD),
        (lambda value: value["seeds"][0].update(extra=True), UNKNOWN_FIELD),
        (lambda value: value["seeds"][0]["provenance"].update(extra=True), UNKNOWN_FIELD),
        (lambda value: value.pop("contract_sha256"), "missing_field"),
    ],
)
def test_manifest_and_nested_records_reject_unknown_or_missing_fields(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    value = _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))])
    mutation(value)
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(value, source_root=tmp_path)
    assert caught.value.code == code


def test_manifest_rejects_duplicate_json_keys_and_non_finite_json(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1","schema_version":"1"}', encoding="utf-8")
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(duplicate)
    assert caught.value.code == MANIFEST_INVALID

    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest('{"score": NaN}')
    assert caught.value.code == MANIFEST_INVALID


def test_manifest_rejects_empty_or_more_than_32_seeds(tmp_path: Path) -> None:
    contract = _contract()
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(_manifest(contract, []), source_root=tmp_path)
    assert caught.value.code == EMPTY_MANIFEST

    records = [_record(f"candidate-{index}.py", f"{index + 1:064x}") for index in range(33)]
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(_manifest(contract, records), source_root=tmp_path)
    assert caught.value.code == TOO_MANY_SEEDS


def test_manifest_rejects_duplicate_sources_and_computed_identities(tmp_path: Path) -> None:
    contract = _contract()
    digest = "1" * 64
    duplicate_source = _manifest(
        contract,
        [_record("same.py", digest), _record("same.py", "2" * 64)],
    )
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(duplicate_source, source_root=tmp_path)
    assert caught.value.code == DUPLICATE_SOURCE

    duplicate_identity = _manifest(
        contract,
        [_record("first.py", digest), _record("second.py", digest)],
    )
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(duplicate_identity, source_root=tmp_path)
    assert caught.value.code == DUPLICATE_IDENTITY


def test_declared_identity_is_verified_and_conflicting_claim_is_a_collision(
    tmp_path: Path,
) -> None:
    contract = _contract()
    base_value = _manifest(contract, [_record("first.py", "1" * 64)])
    parsed = parse_seed_manifest(base_value, source_root=tmp_path)
    claimed = compute_seed_identity(parsed.seeds[0], parsed)

    mismatch = _manifest(contract, [_record("first.py", "1" * 64, identity="seed-wrong")])
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(mismatch, source_root=tmp_path)
    assert caught.value.code == IDENTITY_MISMATCH

    collision = _manifest(
        contract,
        [
            _record("first.py", "1" * 64, identity=claimed),
            _record("second.py", "2" * 64, identity=claimed),
        ],
    )
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(collision, source_root=tmp_path)
    assert caught.value.code == IDENTITY_COLLISION


@pytest.mark.parametrize("source_path", ["../escape.py", "/tmp/absolute.py", "a/../b.py"])
def test_manifest_rejects_escaping_and_absolute_source_paths(
    tmp_path: Path,
    source_path: str,
) -> None:
    contract = _contract()
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(
            _manifest(contract, [_record(source_path, "1" * 64)]),
            source_root=tmp_path,
        )
    assert caught.value.code == SOURCE_UNSAFE


def test_missing_directory_symlink_and_symlink_ancestor_are_never_evaluated(
    tmp_path: Path,
) -> None:
    contract = _contract()
    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    directory = tmp_path / "directory.py"
    directory.mkdir()
    link = tmp_path / "link.py"
    link.symlink_to(target)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    nested = real_parent / "nested.py"
    nested.write_text("x = 2\n", encoding="utf-8")
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    calls = 0

    def evaluator(*_args):
        nonlocal calls
        calls += 1
        return _report()

    cases = [
        (_record("missing.py", "1" * 64), SOURCE_MISSING),
        (_record("directory.py", "1" * 64), SOURCE_NOT_REGULAR),
        (_record("link.py", _sha(target.read_bytes())), SOURCE_UNSAFE),
        (_record("parent-link/nested.py", _sha(nested.read_bytes())), SOURCE_UNSAFE),
    ]
    for index, (record, expected) in enumerate(cases):
        root = tmp_path / f"manifest-{index}"
        root.mkdir()
        # Use the source root explicitly while keeping each manifest filename unique.
        value = _manifest(contract, [record])
        assert _rejection(root, contract, record, evaluator, manifest_root=tmp_path) == expected
        assert value["contract_sha256"] == contract.digest()
    assert calls == 0


def test_source_size_encoding_empty_and_digest_failures_are_fixed_codes(tmp_path: Path) -> None:
    contract = _contract()
    oversized = tmp_path / "oversized.py"
    oversized.write_bytes(b"x" * (512 * 1024 + 1))
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"\xff\xfe")
    empty = tmp_path / "empty.py"
    empty.write_bytes(b"")
    normal = tmp_path / "normal.py"
    normal.write_text("x = 1\n", encoding="utf-8")

    assert (
        _rejection(
            tmp_path,
            contract,
            _record("oversized.py", _sha(oversized.read_bytes())),
            lambda *_: _report(),
        )
        == SOURCE_TOO_LARGE
    )
    assert (
        _rejection(
            tmp_path,
            contract,
            _record("binary.py", _sha(binary.read_bytes())),
            lambda *_: _report(),
        )
        == SOURCE_ENCODING_INVALID
    )
    assert (
        _rejection(
            tmp_path,
            contract,
            _record("empty.py", _sha(empty.read_bytes())),
            lambda *_: _report(),
        )
        == SOURCE_EMPTY
    )
    assert (
        _rejection(
            tmp_path,
            contract,
            _record("normal.py", "1" * 64),
            lambda *_: _report(),
        )
        == SOURCE_DIGEST_MISMATCH
    )


def test_oversized_or_sensitive_metadata_and_invalid_producer_fields_are_rejected(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    digest = _sha(source.read_bytes())
    cases = [
        _record("candidate.py", digest, metadata={"value": "x" * (8 * 1024)}),
        _record("candidate.py", digest, metadata={"prompt": "hidden instructions"}),
        _record("candidate.py", digest, metadata={"note": "api_key=very-secret-value"}),
        _record("candidate.py", digest),
    ]
    cases[-1]["provenance"]["producer_id"] = "bad/producer"

    for record in cases:
        with pytest.raises(SeedAdmissionError):
            parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)


@pytest.mark.parametrize(
    ("field", "replacement", "code"),
    [
        ("contract", _contract("changed-contract"), CONTRACT_MISMATCH),
        ("evaluator_sha", "e" * 64, EVALUATOR_MISMATCH),
        ("dependency_sha", "e" * 64, DEPENDENCY_MISMATCH),
        ("environment_sha", "e" * 64, ENVIRONMENT_MISMATCH),
    ],
)
def test_current_contract_evaluator_dependency_and_environment_are_authoritative(
    tmp_path: Path,
    field: str,
    replacement: object,
    code: str,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    value = _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))])
    kwargs: dict[str, object] = {"manifest_root": tmp_path}
    passed_contract = contract
    if field == "contract":
        passed_contract = replacement
    else:
        kwargs[field] = replacement

    with pytest.raises(SeedAdmissionError) as caught:
        _admit(value, passed_contract, lambda *_: _report(), **kwargs)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("evaluator", "expected"),
    [
        (lambda *_: (_ for _ in ()).throw(RuntimeError("api_key=do-not-store")), EVALUATOR_FAILED),
        (lambda *_: object(), INVALID_EVALUATION_REPORT),
        (lambda *_: _report(validity=0), LOCAL_EVALUATION_INVALID),
        (lambda *_: {**_report(), "combined_score": None}, LOCAL_SCORE_UNAVAILABLE),
        (lambda *_: {**_report(), "unexpected": "payload"}, INVALID_EVALUATION_REPORT),
    ],
)
def test_evaluator_failures_are_rejected_with_fixed_credential_safe_codes(
    tmp_path: Path,
    evaluator,
    expected: str,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    code = _rejection(
        tmp_path,
        contract,
        _record("candidate.py", _sha(source.read_bytes())),
        evaluator,
    )
    assert code == expected
    assert "api_key" not in code
    assert "do-not-store" not in code


def test_external_score_alone_cannot_admit_and_external_requires_exact_harness(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        origin_kind="external",
        external_evidence={"external_score": 1000.0, "producer_validity": 1},
    )
    assert _rejection(tmp_path, contract, record, lambda *_: None) == EXTERNAL_SCORE_ONLY

    value = _manifest(contract, [record], evaluator_kind="model_backed")
    with pytest.raises(SeedAdmissionError) as caught:
        _admit(
            value,
            contract,
            lambda *_: _report(),
            manifest_root=tmp_path,
            evaluator_kind="model_backed",
        )
    assert caught.value.code == NO_USABLE_SEEDS
    assert caught.value.result.rejected[0].code == EXTERNAL_REQUIRES_EXACT_HARNESS


def test_local_seed_can_use_a_declared_non_external_evaluator_kind(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    value = _manifest(
        contract,
        [_record("candidate.py", _sha(source.read_bytes()))],
        evaluator_kind="deterministic_local",
    )
    result = _admit(
        value,
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
        evaluator_kind="deterministic_local",
    )
    assert result.usable_count == 1


def test_evaluator_kind_is_part_of_the_stable_seed_identity(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record("candidate.py", _sha(source.read_bytes()))
    exact = parse_seed_manifest(
        _manifest(contract, [record], evaluator_kind="exact_harness"),
        source_root=tmp_path,
    )
    deterministic = parse_seed_manifest(
        _manifest(contract, [record], evaluator_kind="deterministic_local"),
        source_root=tmp_path,
    )

    assert exact.seeds[0].provenance == deterministic.seeds[0].provenance
    assert compute_seed_identity(exact.seeds[0], exact) != compute_seed_identity(
        deterministic.seeds[0],
        deterministic,
    )
    assert exact.seeds[0].metadata == deterministic.seeds[0].metadata


def test_original_source_mutation_during_evaluation_is_detected(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record("candidate.py", _sha(source.read_bytes()))

    def evaluator(_staged: Path, _contract: AlgorithmProblemContract):
        source.write_text("x = 2\n", encoding="utf-8")
        return _report()

    assert _rejection(tmp_path, contract, record, evaluator) == SOURCE_CHANGED


def test_staged_source_mutation_during_evaluation_is_detected(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record("candidate.py", _sha(source.read_bytes()))

    def evaluator(staged: Path, _contract: AlgorithmProblemContract):
        staged.write_text("x = 3\n", encoding="utf-8")
        return _report()

    assert _rejection(tmp_path, contract, record, evaluator) == STAGED_SOURCE_CHANGED


def test_manifest_object_requires_explicit_source_root_for_admission(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    manifest = parse_seed_manifest(
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))])
    )
    with pytest.raises(SeedAdmissionError) as caught:
        _admit(manifest, contract, lambda *_: _report())
    assert caught.value.code == MANIFEST_ROOT_REQUIRED


def test_receipt_rejects_tampering_and_unknown_fields(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    receipt = _admit(
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
    ).admitted[0].receipt

    tampered = receipt.to_dict()
    tampered["combined_score"] = 999.0
    with pytest.raises(SeedAdmissionError) as caught:
        EvaluatorReceipt.from_dict(tampered)
    assert caught.value.code == INVALID_EVALUATION_REPORT

    unknown = receipt.to_dict()
    unknown["remote_payload"] = {"score": 1}
    with pytest.raises(SeedAdmissionError) as caught:
        EvaluatorReceipt.from_dict(unknown)
    assert caught.value.code == UNKNOWN_FIELD


def test_valid_report_with_error_prose_is_rejected_before_persistence(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    report = EvaluationReport.from_dict(
        {
            **_report(),
            "error_info": [
                {"code": "warning", "message": "arbitrary internal exception detail"}
            ],
        }
    )
    code = _rejection(
        tmp_path,
        contract,
        _record("candidate.py", _sha(source.read_bytes())),
        lambda *_: report,
    )
    assert code == INVALID_EVALUATION_REPORT
    assert "arbitrary internal exception detail" not in code


def test_receipt_requires_the_supported_local_report_schema_version(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    report = EvaluationReport.from_dict({**_report(), "schema_version": "2"})

    code = _rejection(
        tmp_path,
        contract,
        _record("candidate.py", _sha(source.read_bytes())),
        lambda *_: report,
    )

    assert code == INVALID_EVALUATION_REPORT


def test_island_assignment_depends_on_sorted_admitted_identity_not_manifest_order(
    tmp_path: Path,
) -> None:
    contract = _contract()
    sources: dict[str, str] = {}
    for index in range(3):
        path = tmp_path / f"candidate-{index}.py"
        path.write_text(f"x = {index}\n", encoding="utf-8")
        sources[path.name] = _sha(path.read_bytes())
    records = [_record(name, digest) for name, digest in sources.items()]

    first = _admit(
        _manifest(contract, records),
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
        num_islands=2,
    )
    second = _admit(
        _manifest(contract, list(reversed(records))),
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
        num_islands=2,
    )

    first_map = {item.candidate_id: item.island_id for item in first.admitted}
    second_map = {item.candidate_id: item.island_id for item in second.admitted}
    assert first_map == second_map
    assert first_map == {
        candidate_id: index % 2 for index, candidate_id in enumerate(sorted(first_map))
    }


def test_manifest_or_source_root_symlinks_are_rejected(tmp_path: Path) -> None:
    contract = _contract()
    real = tmp_path / "real"
    real.mkdir()
    source = real / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    manifest = _write_manifest(
        real,
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
    )
    linked_manifest = tmp_path / "linked-manifest.json"
    linked_manifest.symlink_to(manifest)
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(linked_manifest)
    assert caught.value.code == SOURCE_UNSAFE

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real, target_is_directory=True)
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(manifest, source_root=linked_root)
    assert caught.value.code == SOURCE_UNSAFE


def test_metadata_that_only_fits_input_limit_cannot_overflow_candidate_metadata(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        metadata={"value": "x" * 7_500},
    )
    assert _rejection(tmp_path, contract, record, lambda *_: _report()) == METADATA_TOO_LARGE


def test_result_and_failure_evidence_are_json_safe_and_bounded(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record("candidate.py", _sha(source.read_bytes()))
    result = _admit(
        _manifest(contract, [record]),
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
    )
    serialized = json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False)
    assert len(serialized.encode("utf-8")) < 64 * 1024
    assert "/Users/" not in serialized
    assert "remote_payload" not in serialized

    code = _rejection(
        tmp_path,
        contract,
        record,
        lambda *_: (_ for _ in ()).throw(RuntimeError("Bearer secret-secret-secret")),
    )
    assert code == EVALUATOR_FAILED


def test_manifest_digest_fields_must_be_lowercase_sha256(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    value = _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))])
    for mutate in (
        lambda item: item.update(contract_sha256="A" * 64),
        lambda item: item["evaluator"].update(fingerprint="short"),
        lambda item: item.update(dependency_sha256="g" * 64),
        lambda item: item.update(environment_sha256=1),
        lambda item: item["seeds"][0].update(source_sha256="A" * 64),
        lambda item: item["seeds"][0]["provenance"].update(
            producer_fingerprint="short"
        ),
    ):
        changed = deepcopy(value)
        mutate(changed)
        with pytest.raises(SeedAdmissionError):
            parse_seed_manifest(changed, source_root=tmp_path)


def test_private_staging_directory_is_removed_even_when_evaluator_fails(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    staging = tmp_path / "staging"
    record = _record("candidate.py", _sha(source.read_bytes()))
    code = _rejection(
        tmp_path,
        contract,
        record,
        lambda *_: (_ for _ in ()).throw(RuntimeError("failure")),
        staging_root=staging,
    )
    assert code == EVALUATOR_FAILED
    assert staging.is_dir()
    assert list(staging.iterdir()) == []


def test_staging_root_symlink_is_rejected_before_evaluator(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    real_staging = tmp_path / "real-staging"
    real_staging.mkdir()
    linked_staging = tmp_path / "linked-staging"
    linked_staging.symlink_to(real_staging, target_is_directory=True)
    calls = 0

    def evaluator(*_args):
        nonlocal calls
        calls += 1
        return _report()

    with pytest.raises(SeedAdmissionError) as caught:
        _admit(
            _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
            contract,
            evaluator,
            manifest_root=tmp_path,
            staging_root=linked_staging,
        )
    assert caught.value.code == SOURCE_UNSAFE
    assert calls == 0


def test_parse_manifest_accepts_strict_json_text_with_explicit_root(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps(_manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]))
    parsed = parse_seed_manifest(text, source_root=tmp_path)
    assert parsed.source_root == tmp_path.resolve()
    assert parsed.to_dict()["schema_version"] == "1"


def test_external_payload_summaries_are_fixed_idempotent_and_drop_raw_values(
    tmp_path: Path,
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        origin_kind="external",
        external_evidence={
            "external_score": 999.0,
            "note": "producer-specific failure prose",
        },
        metadata={"label": "producer-specific label", "fitness": 111.0},
    )
    first = parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)
    second = parse_seed_manifest(first.to_dict(), source_root=tmp_path)

    evidence = first.seeds[0].provenance.external_evidence
    metadata = first.seeds[0].metadata
    assert evidence == second.seeds[0].provenance.external_evidence
    assert metadata == second.seeds[0].metadata
    assert evidence["present"] is True
    assert evidence["score_present"] is True
    assert len(evidence["payload_sha256"]) == 64
    assert metadata["present"] is True
    assert metadata["score_present"] is True
    assert len(metadata["payload_sha256"]) == 64

    admitted = _admit(first, contract, lambda *_: _report()).admitted[0]
    serialized = json.dumps(
        {
            "provenance": admitted.provenance.to_dict(),
            "metadata": admitted.draft.metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    for raw in ("999", "111", "producer-specific failure prose", "producer-specific label"):
        assert raw not in serialized


@pytest.mark.parametrize(
    "summary",
    [
        {"present": False, "score_present": True, "payload_sha256": None},
        {"present": False, "score_present": False, "payload_sha256": "a" * 64},
        {"present": True, "score_present": False, "payload_sha256": None},
        {"present": True, "score_present": False, "payload_sha256": "A" * 64},
    ],
)
def test_external_payload_summary_rejects_inconsistent_or_invalid_digest(
    tmp_path: Path,
    summary: dict[str, object],
) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        origin_kind="external",
        external_evidence=summary,
    )

    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)

    assert caught.value.code == MANIFEST_INVALID


def test_local_seed_metadata_remains_available_after_normalization(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        origin_kind="local",
        metadata={"label": "operator warm start"},
    )

    parsed = parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)

    assert parsed.seeds[0].metadata == {"label": "operator warm start"}


@pytest.mark.parametrize("unsafe", ["\ud800", "line\nbreak.py", "tab\tname.py"])
def test_source_paths_with_surrogates_or_controls_use_a_fixed_error(
    tmp_path: Path,
    unsafe: str,
) -> None:
    contract = _contract()

    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(
            _manifest(contract, [_record(unsafe, "1" * 64)]),
            source_root=tmp_path,
        )

    assert caught.value.code == SOURCE_UNSAFE


def test_metadata_controls_and_deep_json_use_fixed_manifest_errors(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    record = _record(
        "candidate.py",
        _sha(source.read_bytes()),
        metadata={"note": "line\nbreak"},
    )

    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)
    assert caught.value.code == MANIFEST_INVALID

    deeply_nested = "[" * 10_000 + "0" + "]" * 10_000
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(deeply_nested, source_root=tmp_path)
    assert caught.value.code == MANIFEST_INVALID


@pytest.mark.parametrize("unsafe", ["\ud800", "line\nbreak", "tab\tref"])
def test_material_references_with_surrogates_or_controls_use_a_fixed_error(
    tmp_path: Path,
    unsafe: str,
) -> None:
    contract = _contract()
    record = _record("candidate.py", "1" * 64)
    record["provenance"]["material_refs"] = [unsafe]  # type: ignore[index]

    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest(_manifest(contract, [record]), source_root=tmp_path)

    assert caught.value.code == MANIFEST_INVALID


def test_json_text_with_a_literal_surrogate_uses_a_fixed_manifest_error() -> None:
    with pytest.raises(SeedAdmissionError) as caught:
        parse_seed_manifest('{"value":"\ud800"}')

    assert caught.value.code == MANIFEST_INVALID


def test_evaluator_receives_original_contract_object(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    received: list[AlgorithmProblemContract] = []

    def evaluator(_path: Path, value: AlgorithmProblemContract):
        received.append(value)
        return _report()

    _admit(
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
        contract,
        evaluator,
        manifest_root=tmp_path,
    )
    assert received == [contract]


def test_invalid_num_islands_fails_before_evaluation(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    calls = 0

    def evaluator(*_args):
        nonlocal calls
        calls += 1
        return _report()

    with pytest.raises(SeedAdmissionError) as caught:
        _admit(
            _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
            contract,
            evaluator,
            manifest_root=tmp_path,
            num_islands=0,
        )
    assert caught.value.code == MANIFEST_INVALID
    assert calls == 0


def test_source_file_permissions_do_not_change_during_admission(tmp_path: Path) -> None:
    contract = _contract()
    source = tmp_path / "candidate.py"
    source.write_text("x = 1\n", encoding="utf-8")
    os.chmod(source, 0o640)
    before = source.stat().st_mode & 0o777
    _admit(
        _manifest(contract, [_record("candidate.py", _sha(source.read_bytes()))]),
        contract,
        lambda *_: _report(),
        manifest_root=tmp_path,
    )
    assert source.stat().st_mode & 0o777 == before
