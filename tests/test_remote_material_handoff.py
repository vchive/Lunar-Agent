from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.producer_handoff import ProducerHandoffError
from famou.remote_evolution import (
    RemoteExperimentState,
    RemoteMaterialReference,
)
from famou.remote_material_handoff import (
    REMOTE_HANDOFF_BUDGET_INVALID,
    REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED,
    REMOTE_HANDOFF_IDENTITY_MISMATCH,
    REMOTE_HANDOFF_MATERIAL_KIND_UNSUPPORTED,
    REMOTE_HANDOFF_MATERIALS_EMPTY,
    REMOTE_HANDOFF_NOT_COMPLETED,
    REMOTE_HANDOFF_RECONCILIATION_INVALID,
    REMOTE_HANDOFF_STAGING_ROOT_UNSAFE,
    REMOTE_HANDOFF_STATE_INVALID,
    RemoteMaterialHandoffError,
    admit_remote_materials,
    remote_state_to_producer_envelope,
)

CONTRACT_SHA = "a" * 64
PRODUCER_SHA = "b" * 64
EVALUATOR_SHA = "c" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "remote-material-fixture",
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


def _source(root: Path, path: str = "submission/init.py", text: str = "answer = 1\n") -> RemoteMaterialReference:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    content = target.read_bytes()
    return RemoteMaterialReference(
        kind="candidate_source",
        path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _state(
    root: Path,
    *,
    status: str = "completed",
    experiment_id: str | None = "experiment:1",
    producer_id: str = "famou-v2",
    producer_fingerprint: str = PRODUCER_SHA,
    materials: tuple[RemoteMaterialReference, ...] | None = None,
) -> RemoteExperimentState:
    if materials is None:
        materials = (_source(root),)
    return RemoteExperimentState(
        experiment_id=experiment_id,
        idempotency_key="submission-1",
        producer_id=producer_id,
        producer_fingerprint=producer_fingerprint,
        status=status,  # type: ignore[arg-type]
        submitted_at_ms=100,
        updated_at_ms=200,
        attempt_count=2,
        materials=materials,
    )


def _report(score: float = 0.25) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "remote-local-exact",
            "validity": 1,
            "quality": score,
            "combined_score": score,
            "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
            "error_info": [],
        }
    )


def _admit(root: Path, *, evaluator=None, **kwargs):
    contract = _contract()
    return admit_remote_materials(
        root,
        _state(root),
        contract,
        evaluator or (lambda path, supplied: _report()),
        evaluator_fingerprint=EVALUATOR_SHA,
        producer_id="famou-v2",
        producer_fingerprint=PRODUCER_SHA,
        budget={"max_iterations": 3},
        staging_root=root.parent / "staging",
        **kwargs,
    )


def test_completed_remote_state_maps_to_digest_only_envelope(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    state = _state(root)

    envelope = remote_state_to_producer_envelope(
        state,
        contract_sha256=_contract().digest(),
        producer_id="famou-v2",
        producer_fingerprint=PRODUCER_SHA,
        budget={"max_iterations": 3},
    )

    assert envelope.status == "completed"
    assert envelope.producer_run_id is not None
    assert envelope.producer_run_id.startswith("remote-")
    assert envelope.materials[0].path == "submission/init.py"
    assert envelope.external_evidence["present"] is True
    assert envelope.external_evidence["score_present"] is False
    assert len(envelope.external_evidence["payload_sha256"]) == 64
    assert "experiment:1" not in str(envelope.external_evidence)


def test_remote_materials_use_local_evaluator_and_preserve_reference_digest(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    calls: list[Path] = []

    def evaluator(path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        calls.append(path)
        assert contract == _contract()
        return _report(0.75)

    result = _admit(root, evaluator=evaluator)

    assert len(calls) == 1
    assert len(result.admitted) == 1
    admitted = result.admitted[0]
    assert admitted.evaluation.combined_score == 0.75
    assert admitted.receipt.evaluator_kind == "exact_harness"
    assert admitted.provenance.origin_kind == "external"
    assert admitted.provenance.producer_id == "famou-v2"
    assert admitted.provenance.material_refs == ("submission/init.py",)
    assert admitted.provenance.external_evidence["score_present"] is False


@pytest.mark.parametrize("status", ["submitted", "running", "unknown", "failed", "cancelled"])
def test_non_completed_remote_state_fails_before_local_evaluator(tmp_path: Path, status: str) -> None:
    root = tmp_path / "materials"
    state = _state(root, status=status)
    calls: list[Path] = []

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        admit_remote_materials(
            root,
            state,
            _contract(),
            lambda path, contract: calls.append(path) or _report(),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )

    assert caught.value.code == REMOTE_HANDOFF_NOT_COMPLETED
    assert calls == []


def test_completed_state_requires_an_experiment_id(tmp_path: Path) -> None:
    state = _state(tmp_path / "materials")
    object.__setattr__(state, "experiment_id", None)
    with pytest.raises(RemoteMaterialHandoffError) as caught:
        admit_remote_materials(
            tmp_path,
            state,
            _contract(),
            lambda path, contract: _report(),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == REMOTE_HANDOFF_EXPERIMENT_ID_REQUIRED


def test_empty_materials_and_identity_drift_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    empty = _state(root, materials=())
    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            empty,
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == REMOTE_HANDOFF_MATERIALS_EMPTY

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            _state(root),
            contract_sha256=_contract().digest(),
            producer_id="other-producer",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == REMOTE_HANDOFF_IDENTITY_MISMATCH


def test_unsupported_material_kind_is_rejected_before_read(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    reference = _source(root)
    bad = replace(reference, kind="artifact")
    state = _state(root, materials=(bad,))

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            state,
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == REMOTE_HANDOFF_MATERIAL_KIND_UNSUPPORTED


def test_reconciliation_is_required_when_previous_state_is_supplied(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    previous = _state(root, status="running")
    observed = _state(root, status="completed", experiment_id="different")

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            observed,
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
            previous_state=previous,
        )
    assert caught.value.code == REMOTE_HANDOFF_RECONCILIATION_INVALID


def test_material_digest_and_path_checks_remain_in_generic_boundary(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    reference = _source(root)
    (root / reference.path).write_text("answer = 2\n", encoding="utf-8")
    state = _state(root, materials=(reference,))

    with pytest.raises(ProducerHandoffError) as caught:
        admit_remote_materials(
            root,
            state,
            _contract(),
            lambda path, supplied: _report(),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == "producer_material_digest_mismatch"


def test_invalid_budget_fails_before_any_material_or_evaluator_work(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            _state(root),
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={},
        )
    assert caught.value.code == REMOTE_HANDOFF_BUDGET_INVALID


def test_malicious_budget_mapping_is_contained_by_fixed_error(tmp_path: Path) -> None:
    class ExplodingMapping(dict):
        def __iter__(self):
            raise RuntimeError("mapping iterator must not escape")

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            _state(tmp_path / "materials"),
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget=ExplodingMapping(max_iterations=3),
        )
    assert caught.value.code == REMOTE_HANDOFF_BUDGET_INVALID


def test_forged_frozen_state_is_revalidated_before_material_admission(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    state = _state(root)
    object.__setattr__(state, "attempt_count", 0)
    with pytest.raises(RemoteMaterialHandoffError) as caught:
        remote_state_to_producer_envelope(
            state,
            contract_sha256=_contract().digest(),
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
        )
    assert caught.value.code == REMOTE_HANDOFF_STATE_INVALID


def test_bridge_does_not_invoke_a_backend(tmp_path: Path) -> None:
    class Backend:
        calls = 0

        def sync(self, request):
            self.calls += 1
            raise AssertionError("remote backend must not be called")

    backend = Backend()
    result = _admit(tmp_path / "materials")
    assert result.usable_count == 1
    assert backend.calls == 0


def test_staging_root_must_be_disjoint_without_mutating_material_root(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    state = _state(root)
    nested = root / "local-staging"
    calls: list[Path] = []

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        admit_remote_materials(
            root,
            state,
            _contract(),
            lambda path, supplied: calls.append(path) or _report(),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
            staging_root=nested,
        )

    assert caught.value.code == REMOTE_HANDOFF_STAGING_ROOT_UNSAFE
    assert calls == []
    assert not nested.exists()


@pytest.mark.parametrize("nested", [False, True])
def test_staging_root_case_alias_is_rejected_on_case_insensitive_filesystem(
    tmp_path: Path, *, nested: bool
) -> None:
    root = tmp_path / "MaterialRoot"
    state = _state(root)
    alias = tmp_path / "materialroot"
    try:
        same_directory = os.path.samefile(root, alias)
    except OSError:
        same_directory = False
    if not same_directory:
        pytest.skip("requires a case-insensitive filesystem")

    staging = alias / "local-staging" if nested else alias
    before = {path.relative_to(root) for path in root.rglob("*")}
    calls: list[Path] = []

    with pytest.raises(RemoteMaterialHandoffError) as caught:
        admit_remote_materials(
            root,
            state,
            _contract(),
            lambda path, supplied: calls.append(path) or _report(),
            evaluator_fingerprint=EVALUATOR_SHA,
            producer_id="famou-v2",
            producer_fingerprint=PRODUCER_SHA,
            budget={"max_iterations": 3},
            staging_root=staging,
        )

    assert caught.value.code == REMOTE_HANDOFF_STAGING_ROOT_UNSAFE
    assert calls == []
    assert {path.relative_to(root) for path in root.rglob("*")} == before
