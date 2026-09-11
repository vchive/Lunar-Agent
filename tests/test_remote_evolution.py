from __future__ import annotations

import json
from dataclasses import replace

import pytest

from famou.remote_evolution import (
    MAX_REMOTE_ATTEMPTS,
    MAX_REMOTE_ITERATIONS,
    MAX_REMOTE_MATERIAL_BYTES,
    MAX_REMOTE_MATERIALS,
    RemoteCancelRequest,
    RemoteContinueRequest,
    RemoteEvolutionBackend,
    RemoteEvolutionError,
    RemoteExperimentReference,
    RemoteExperimentState,
    RemoteMaterialReference,
    RemoteStatusRequest,
    RemoteSubmitRequest,
    RemoteSyncRequest,
    cancel,
    continue_experiment,
    reconcile_remote_state,
    status,
    submit,
    sync,
)

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
PRODUCER_ID = "famou-v2"
PRODUCER_FINGERPRINT = "c" * 64


def material(
    path: str = "submission/init.py",
    *,
    kind: str = "candidate_source",
    size: int = 17,
    sha256: str = DIGEST,
) -> RemoteMaterialReference:
    return RemoteMaterialReference(kind=kind, path=path, size=size, sha256=sha256)


def state(
    lifecycle: str,
    *,
    experiment_id: str | None = "experiment-1",
    idempotency_key: str = "submission-1",
    producer_id: str = PRODUCER_ID,
    producer_fingerprint: str = PRODUCER_FINGERPRINT,
    attempt_count: int = 1,
    submitted_at_ms: int | None = 100,
    updated_at_ms: int | None = 100,
    materials: tuple[RemoteMaterialReference, ...] | None = None,
) -> RemoteExperimentState:
    return RemoteExperimentState(
        experiment_id=experiment_id,
        idempotency_key=idempotency_key,
        producer_id=producer_id,
        producer_fingerprint=producer_fingerprint,
        status=lifecycle,  # type: ignore[arg-type]
        submitted_at_ms=submitted_at_ms,
        updated_at_ms=updated_at_ms,
        attempt_count=attempt_count,
        materials=(material(),) if materials is None else materials,
    )


class FakeBackend:
    def __init__(self, **outcomes: object) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, object]] = []

    def _result(self, operation: str, request: object) -> RemoteExperimentState:
        self.calls.append((operation, request))
        result = self.outcomes[operation]
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]

    def submit(self, request: RemoteSubmitRequest) -> RemoteExperimentState:
        return self._result("submit", request)

    def status(self, request: RemoteStatusRequest) -> RemoteExperimentState:
        return self._result("status", request)

    def sync(self, request: RemoteSyncRequest) -> RemoteExperimentState:
        return self._result("sync", request)

    def continue_experiment(self, request: RemoteContinueRequest) -> RemoteExperimentState:
        return self._result("continue", request)

    def cancel(self, request: RemoteCancelRequest) -> RemoteExperimentState:
        return self._result("cancel", request)


def submit_request() -> RemoteSubmitRequest:
    return RemoteSubmitRequest(
        idempotency_key="submission-1",
        producer_id=PRODUCER_ID,
        producer_fingerprint=PRODUCER_FINGERPRINT,
        problem_id="routing-1",
        contract_sha256=DIGEST,
        max_iterations=5,
        materials=(material(),),
    )


def test_remote_dtos_round_trip_through_strict_json_objects() -> None:
    submitted = submit_request()
    current = state("running", attempt_count=2, updated_at_ms=200)
    dto_pairs = (
        (RemoteMaterialReference, material()),
        (RemoteExperimentReference, current.reference),
        (RemoteSubmitRequest, submitted),
        (RemoteStatusRequest, RemoteStatusRequest.from_state(current)),
        (RemoteSyncRequest, RemoteSyncRequest.from_state(current)),
        (
            RemoteContinueRequest,
            RemoteContinueRequest.from_state(current, "continue-1", 3),
        ),
        (RemoteCancelRequest, RemoteCancelRequest.from_state(current, "cancel-1")),
        (RemoteExperimentState, current),
    )

    for dto_type, value in dto_pairs:
        encoded = json.loads(json.dumps(value.to_dict(), sort_keys=True))
        assert dto_type.from_dict(encoded) == value


@pytest.mark.parametrize(
    ("factory", "payload"),
    [
        (
            RemoteSubmitRequest.from_dict,
            {
                **submit_request().to_dict(),
                "endpoint": "https://remote.invalid",
            },
        ),
        (
            RemoteStatusRequest.from_dict,
            {
                **RemoteStatusRequest(
                    "experiment-1",
                    "submission-1",
                    PRODUCER_ID,
                    PRODUCER_FINGERPRINT,
                ).to_dict(),
                "retry": True,
            },
        ),
        (
            RemoteExperimentState.from_dict,
            {**state("running").to_dict(), "combined_score": 100.0},
        ),
        (
            RemoteMaterialReference.from_dict,
            {**material().to_dict(), "evaluation": {"validity": 1}},
        ),
    ],
)
def test_remote_dtos_reject_unknown_fields(factory: object, payload: dict[str, object]) -> None:
    with pytest.raises(RemoteEvolutionError, match="unsupported"):
        factory(payload)  # type: ignore[operator]


def test_remote_requests_reject_wrong_schema_and_credentials() -> None:
    payload = submit_request().to_dict()
    payload["schema_version"] = "2"
    with pytest.raises(RemoteEvolutionError, match="schema_version"):
        RemoteSubmitRequest.from_dict(payload)

    with pytest.raises(RemoteEvolutionError, match="credential"):
        RemoteMaterialReference(
            kind="candidate_source",
            path="submission/api_key=super-secret",
            size=1,
            sha256=DIGEST,
        )
    with pytest.raises(RemoteEvolutionError, match="safe bounded identifier"):
        RemoteSubmitRequest(
            "bad key",
            PRODUCER_ID,
            PRODUCER_FINGERPRINT,
            "routing",
            DIGEST,
            1,
            (material(),),
        )


@pytest.mark.parametrize(
    ("dto_type", "payload"),
    [
        (RemoteSubmitRequest, submit_request().to_dict()),
        (RemoteStatusRequest, RemoteStatusRequest.from_state(state("running")).to_dict()),
        (RemoteSyncRequest, RemoteSyncRequest.from_state(state("running")).to_dict()),
        (RemoteExperimentState, state("running").to_dict()),
    ],
)
@pytest.mark.parametrize("field", ["producer_id", "producer_fingerprint"])
def test_producer_identity_is_required_by_every_lifecycle_dto(
    dto_type: object, payload: dict[str, object], field: str
) -> None:
    payload = dict(payload)
    payload.pop(field)
    with pytest.raises(RemoteEvolutionError, match=f"missing {field}"):
        dto_type.from_dict(payload)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "bad_path",
    ("/absolute.py", "../escape.py", "submission/../escape.py", "submission\\file.py", ""),
)
def test_material_paths_are_confined_posix_paths(bad_path: str) -> None:
    with pytest.raises(RemoteEvolutionError, match="relative path"):
        material(bad_path)


def test_material_and_request_bounds_are_enforced() -> None:
    with pytest.raises(RemoteEvolutionError, match="material size"):
        material(size=MAX_REMOTE_MATERIAL_BYTES + 1)
    with pytest.raises(RemoteEvolutionError, match="max_iterations"):
        replace(submit_request(), max_iterations=MAX_REMOTE_ITERATIONS + 1)
    with pytest.raises(RemoteEvolutionError, match="paths must be unique"):
        replace(submit_request(), materials=(material(), material()))
    too_many = tuple(material(f"submission/{index}.py") for index in range(MAX_REMOTE_MATERIALS + 1))
    with pytest.raises(RemoteEvolutionError, match="bounded"):
        replace(submit_request(), materials=too_many)


def test_remote_state_requires_id_except_for_explicit_unknown() -> None:
    unknown = state("unknown", experiment_id=None, submitted_at_ms=None, updated_at_ms=None)
    assert unknown.experiment_id is None
    assert unknown.lifecycle_state == "unknown"
    assert not unknown.terminal

    with pytest.raises(RemoteEvolutionError, match="only for unknown"):
        state("submitted", experiment_id=None)
    with pytest.raises(RemoteEvolutionError, match="status is unsupported"):
        state("invented")
    with pytest.raises(RemoteEvolutionError, match="attempt_count"):
        state("running", attempt_count=MAX_REMOTE_ATTEMPTS + 1)
    with pytest.raises(RemoteEvolutionError, match="must not precede"):
        state("running", submitted_at_ms=200, updated_at_ms=199)


def test_mutating_requests_require_a_reconciled_experiment_id() -> None:
    with pytest.raises(RemoteEvolutionError, match="continue requires"):
        RemoteContinueRequest(
            None,  # type: ignore[arg-type]
            "submission-1",
            "openevolve",
            DIGEST,
            "continue-1",
            1,
        )
    with pytest.raises(RemoteEvolutionError, match="cancel requires"):
        RemoteCancelRequest(
            None,  # type: ignore[arg-type]
            "submission-1",
            "openevolve",
            DIGEST,
            "cancel-1",
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("submitted", "running"),
        ("submitted", "unknown"),
        ("submitted", "cancelled"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "unknown"),
        ("running", "cancelled"),
        ("unknown", "running"),
        ("unknown", "completed"),
        ("unknown", "failed"),
    ],
)
def test_legal_remote_transitions(before: str, after: str) -> None:
    prior = state(before, updated_at_ms=100)
    observed = state(after, attempt_count=2, updated_at_ms=200)
    assert reconcile_remote_state(prior, observed) == observed


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("submitted", "completed"),
        ("submitted", "failed"),
        ("running", "submitted"),
        ("unknown", "submitted"),
        ("unknown", "cancelled"),
        ("completed", "running"),
        ("cancelled", "running"),
        ("failed", "running"),
    ],
)
def test_illegal_remote_transitions_are_rejected(before: str, after: str) -> None:
    with pytest.raises(RemoteEvolutionError, match="illegal remote state transition"):
        reconcile_remote_state(
            state(before, updated_at_ms=100),
            state(after, attempt_count=2, updated_at_ms=200),
        )


def test_unknown_without_id_must_reconcile_id_before_terminal_state() -> None:
    missing_id = state(
        "unknown", experiment_id=None, submitted_at_ms=None, updated_at_ms=None, materials=()
    )
    with_id = state(
        "unknown",
        experiment_id="experiment-found",
        attempt_count=2,
        submitted_at_ms=100,
        updated_at_ms=200,
        materials=(),
    )
    assert reconcile_remote_state(missing_id, with_id) == with_id

    completed = replace(with_id, status="completed", attempt_count=3, updated_at_ms=300)
    assert reconcile_remote_state(with_id, completed) == completed
    with pytest.raises(RemoteEvolutionError, match="must first reconcile"):
        reconcile_remote_state(missing_id, completed)


def test_reconciliation_binds_identity_time_attempts_and_materials() -> None:
    prior = state("running", attempt_count=3, updated_at_ms=300)
    new_material = material("sync/candidate.py", sha256=OTHER_DIGEST)
    observed = state(
        "running",
        attempt_count=4,
        updated_at_ms=400,
        materials=(*prior.materials, new_material),
    )
    assert reconcile_remote_state(prior, observed) == observed

    failures = (
        replace(observed, experiment_id="other-experiment"),
        replace(observed, idempotency_key="other-key"),
        replace(observed, producer_id="other-producer"),
        replace(observed, producer_fingerprint=OTHER_DIGEST),
        replace(observed, attempt_count=2),
        replace(observed, submitted_at_ms=101),
        replace(observed, updated_at_ms=200),
        replace(observed, materials=(new_material,)),
        replace(
            observed,
            materials=(replace(prior.materials[0], sha256=OTHER_DIGEST), new_material),
        ),
    )
    for changed in failures:
        with pytest.raises(RemoteEvolutionError):
            reconcile_remote_state(prior, changed)


def test_terminal_state_is_byte_semantically_immutable() -> None:
    terminal = state("completed", attempt_count=3, updated_at_ms=300)
    assert reconcile_remote_state(terminal, terminal) is terminal
    with pytest.raises(RemoteEvolutionError, match="terminal remote state is immutable"):
        reconcile_remote_state(terminal, replace(terminal, attempt_count=4, updated_at_ms=400))


def test_fake_backend_satisfies_runtime_protocol() -> None:
    backend = FakeBackend()
    assert isinstance(backend, RemoteEvolutionBackend)


def test_submit_calls_backend_once_and_validates_identity_and_materials() -> None:
    request = submit_request()
    response = state("submitted")
    backend = FakeBackend(submit=response)
    assert submit(backend, request) == response
    assert backend.calls == [("submit", request)]

    wrong_key = FakeBackend(submit=replace(response, idempotency_key="other-key"))
    with pytest.raises(RemoteEvolutionError, match="does not match"):
        submit(wrong_key, request)

    wrong_producer = FakeBackend(submit=replace(response, producer_id="other-producer"))
    with pytest.raises(RemoteEvolutionError, match="producer_id does not match"):
        submit(wrong_producer, request)
    wrong_fingerprint = FakeBackend(
        submit=replace(response, producer_fingerprint=OTHER_DIGEST)
    )
    with pytest.raises(RemoteEvolutionError, match="producer_fingerprint does not match"):
        submit(wrong_fingerprint, request)

    missing_material = FakeBackend(submit=replace(response, materials=()))
    with pytest.raises(RemoteEvolutionError, match="omitted or changed"):
        submit(missing_material, request)


@pytest.mark.parametrize("outcome", [TimeoutError("private timeout"), OSError("private I/O"), None])
def test_uncertain_submit_becomes_score_free_unknown_without_retry(outcome: object) -> None:
    request = submit_request()
    backend = FakeBackend(submit=outcome)
    result = submit(backend, request)
    assert result.status == "unknown"
    assert result.experiment_id is None
    assert result.idempotency_key == request.idempotency_key
    assert result.producer_id == request.producer_id
    assert result.producer_fingerprint == request.producer_fingerprint
    assert result.materials == request.materials
    assert result.to_dict().keys().isdisjoint({"error", "score", "cost", "usage"})
    assert len(backend.calls) == 1


def test_status_and_sync_reconcile_once_and_keep_material_score_free() -> None:
    prior = state("submitted")
    running = state("running", attempt_count=2, updated_at_ms=200)
    status_request = RemoteStatusRequest.from_state(prior)
    status_backend = FakeBackend(status=running)
    assert status(status_backend, status_request, prior) == running
    assert status_backend.calls == [("status", status_request)]

    synchronized = replace(
        running,
        status="completed",
        attempt_count=3,
        updated_at_ms=300,
        materials=(*running.materials, material("sync/final.py", sha256=OTHER_DIGEST)),
    )
    sync_request = RemoteSyncRequest.from_state(running)
    sync_backend = FakeBackend(sync=synchronized)
    result = sync(sync_backend, sync_request, running)
    assert result == synchronized
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert "combined_score" not in encoded
    assert "evaluation" not in encoded
    assert sync_backend.calls == [("sync", sync_request)]


def test_status_timeout_marks_nonterminal_unknown_and_never_retries() -> None:
    prior = state("running", attempt_count=3, updated_at_ms=300)
    request = RemoteStatusRequest.from_state(prior)
    backend = FakeBackend(status=TimeoutError("not persisted"))
    result = status(backend, request, prior)
    assert result.status == "unknown"
    assert result.experiment_id == prior.experiment_id
    assert result.attempt_count == 4
    assert len(backend.calls) == 1


def test_mismatched_request_is_rejected_before_backend_invocation() -> None:
    prior = state("running")
    backend = FakeBackend(status=prior)
    request = RemoteStatusRequest(
        "other-experiment",
        prior.idempotency_key,
        prior.producer_id,
        prior.producer_fingerprint,
    )
    with pytest.raises(RemoteEvolutionError, match="experiment_id does not match"):
        status(backend, request, prior)
    assert backend.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("producer_id", "other-producer"), ("producer_fingerprint", OTHER_DIGEST)],
)
def test_followup_request_rejects_producer_drift_before_backend_invocation(
    field: str, value: str
) -> None:
    prior = state("running")
    backend = FakeBackend(status=prior)
    request = replace(RemoteStatusRequest.from_state(prior), **{field: value})
    with pytest.raises(RemoteEvolutionError, match=f"{field} does not match"):
        status(backend, request, prior)
    assert backend.calls == []


@pytest.mark.parametrize("terminal_status", ["completed", "cancelled", "failed"])
def test_continue_and_cancel_reject_terminal_state_before_backend_call(
    terminal_status: str,
) -> None:
    terminal = state(terminal_status)
    backend = FakeBackend(**{"continue": terminal, "cancel": terminal})

    with pytest.raises(RemoteEvolutionError, match="terminal"):
        RemoteContinueRequest.from_state(terminal, "continue-1", 1)
    with pytest.raises(RemoteEvolutionError, match="terminal"):
        RemoteCancelRequest.from_state(terminal, "cancel-1")

    continue_request = RemoteContinueRequest(
        terminal.experiment_id,  # type: ignore[arg-type]
        terminal.idempotency_key,
        terminal.producer_id,
        terminal.producer_fingerprint,
        "continue-1",
        1,
    )
    cancel_request = RemoteCancelRequest(
        terminal.experiment_id,  # type: ignore[arg-type]
        terminal.idempotency_key,
        terminal.producer_id,
        terminal.producer_fingerprint,
        "cancel-1",
    )
    with pytest.raises(RemoteEvolutionError, match="terminal"):
        continue_experiment(backend, continue_request, terminal)
    with pytest.raises(RemoteEvolutionError, match="terminal"):
        cancel(backend, cancel_request, terminal)
    assert backend.calls == []


def test_continue_and_cancel_are_single_call_idempotent_operations() -> None:
    running = state("running", attempt_count=2, updated_at_ms=200)
    continue_request = RemoteContinueRequest.from_state(running, "continue-1", 2)
    continued = replace(running, attempt_count=3, updated_at_ms=300)
    continue_backend = FakeBackend(**{"continue": continued})
    assert continue_experiment(continue_backend, continue_request, running) == continued
    assert continue_backend.calls == [("continue", continue_request)]

    cancel_request = RemoteCancelRequest.from_state(continued, "cancel-1")
    cancelled = replace(
        continued, status="cancelled", attempt_count=4, updated_at_ms=400
    )
    cancel_backend = FakeBackend(cancel=cancelled)
    assert cancel(cancel_backend, cancel_request, continued) == cancelled
    assert cancel_backend.calls == [("cancel", cancel_request)]


def test_uncertain_continue_and_cancel_do_not_invent_terminal_outcomes() -> None:
    running = state("running", attempt_count=2, updated_at_ms=200)
    continue_request = RemoteContinueRequest.from_state(running, "continue-1", 2)
    continue_backend = FakeBackend(**{"continue": TimeoutError("secret detail")})
    uncertain = continue_experiment(continue_backend, continue_request, running)
    assert uncertain.status == "unknown"
    assert uncertain.experiment_id == running.experiment_id
    assert len(continue_backend.calls) == 1

    # Unknown remains non-terminal, but the state machine will not claim cancellation from an
    # ambiguous response. A subsequent status observation must reconcile the experiment first.
    cancel_request = RemoteCancelRequest.from_state(uncertain, "cancel-1")
    cancel_backend = FakeBackend(cancel=None)
    still_unknown = cancel(cancel_backend, cancel_request, uncertain)
    assert still_unknown.status == "unknown"
    assert len(cancel_backend.calls) == 1


def test_remote_state_schema_cannot_carry_score_cost_usage_or_exception_text() -> None:
    payload = state("unknown").to_dict()
    for forbidden, value in (
        ("combined_score", 9.0),
        ("validity", 1),
        ("cost", 12),
        ("usage", {"tokens": 1}),
        ("error", "private exception"),
    ):
        with pytest.raises(RemoteEvolutionError, match="unsupported"):
            RemoteExperimentState.from_dict({**payload, forbidden: value})
