"""Offline registration, launch preflight, and one-slot ledger fixtures."""
from __future__ import annotations

import copy

import pytest
from measurement139_support import campaign, complete_campaign, new_campaign


def test_default_registration_is_fixed_and_push_pinned():
    manifest = campaign.default_manifest()
    validated = campaign.validate_registration(manifest, head="abc", origin="abc")
    assert validated == manifest
    assert validated["planned_attempts"] == 1
    assert validated["retries_or_replacements"] == 0
    assert validated["budgets"]["max_requests"] == 20
    assert "endpoint" not in validated["provider"]


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("product_commit", "different-pin", "product_pin_drift"),
        ("task_sha256", "0" * 64, "task_or_input_drift"),
        ("input_sha256", "0" * 64, "task_or_input_drift"),
        ("attempt_id", "attempt-002", "attempt_slot_mismatch"),
        ("planned_attempts", 2, "one_slot_contract_violation"),
        ("retries_or_replacements", 1, "one_slot_contract_violation"),
    ],
)
def test_registration_rejects_drift(field, value, error):
    manifest = campaign.default_manifest()
    manifest[field] = value
    with pytest.raises(campaign.RegistrationError, match=error):
        campaign.validate_registration(manifest)


def test_registration_rejects_dirty_unpushed_reused_root_and_identity():
    manifest = campaign.default_manifest()
    with pytest.raises(campaign.RegistrationError, match="worktree_dirty"):
        campaign.validate_registration(manifest, worktree_clean=False)
    with pytest.raises(campaign.RegistrationError, match="registration_not_pushed"):
        campaign.validate_registration(manifest, head="new", origin="old")
    with pytest.raises(campaign.RegistrationError, match="campaign_root_unavailable"):
        campaign.validate_registration(manifest, existing_roots={manifest["campaign_root"]})
    with pytest.raises(campaign.RegistrationError, match="duplicate_identity"):
        campaign.validate_registration(manifest, existing_ids={manifest["campaign_id"]})
    with pytest.raises(campaign.RegistrationError, match="historical_identity_reuse"):
        campaign.validate_registration(manifest, historical_ids={manifest["registration_id"]})


def test_registration_rejects_provider_and_budget_policy_drift():
    manifest = campaign.default_manifest()
    manifest["provider"] = {"kind": "openai-compatible", "model": "other-model"}
    with pytest.raises(campaign.RegistrationError, match="provider_identity_drift"):
        campaign.validate_registration(manifest)
    manifest = campaign.default_manifest()
    manifest["budgets"] = copy.deepcopy(manifest["budgets"])
    manifest["budgets"]["candidate_steps"] = 13
    with pytest.raises(campaign.RegistrationError, match="budget_drift"):
        campaign.validate_registration(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_seconds", 601),
        ("preparation_request_timeout_seconds", 901),
        ("preparation_wall_seconds", 1861),
        ("wall_seconds", 2401),
        ("max_requests", 21),
        ("observed_token_stop", 160001),
    ],
)
def test_registration_rejects_each_budget_policy_change(field, value):
    manifest = campaign.default_manifest()
    manifest["budgets"] = copy.deepcopy(manifest["budgets"])
    manifest["budgets"][field] = value
    with pytest.raises(campaign.RegistrationError, match="budget_drift"):
        campaign.validate_registration(manifest)


def test_request_ledger_is_sequential_and_consumes_slot_once():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=20, token_stop_threshold=10)
    assert ledger.begin(now=0)["index"] == 1
    with pytest.raises(campaign.CampaignError, match="request_index_not_sequential"):
        ledger.begin(index=3, now=1)
    ledger.finish(1, outcome="completed", now=2, observed_tokens=4, transport_status=200)
    assert ledger.begin(now=3)["index"] == 2
    ledger.finish(2, outcome="failed", now=4, observed_tokens=1, transport_status=503)
    with pytest.raises(campaign.CampaignError, match="request_slot_closed"):
        ledger.begin(now=5)
    assert ledger.snapshot() == {
        "provider_requests": 2,
        "finished_requests": 2,
        "pending_requests": [],
        "observed_tokens": 5,
        "usage_complete": True,
        "transport_statuses": [200, 503],
        "closed": True,
    }


def test_request_ledger_stops_before_deadline_or_token_threshold():
    ledger = campaign.RequestLedger(max_requests=20, wall_seconds=5, token_stop_threshold=10)
    with pytest.raises(campaign.CampaignError, match="attempt_deadline_reached"):
        ledger.begin(now=5)
    ledger = campaign.RequestLedger(max_requests=20, wall_seconds=50, token_stop_threshold=10)
    ledger.begin(now=0)
    ledger.finish(1, outcome="completed", now=1, observed_tokens=10)
    with pytest.raises(campaign.CampaignError, match="request_slot_closed"):
        ledger.begin(now=2)


def test_request_ledger_rejects_pending_close_and_bad_transport():
    ledger = campaign.RequestLedger(max_requests=2)
    ledger.begin(now=0)
    with pytest.raises(campaign.CampaignError, match="pending_request"):
        ledger.close()
    with pytest.raises(campaign.CampaignError, match="invalid_transport_status"):
        ledger.finish(1, outcome="unknown", now=1, transport_status=99)


def test_request_ledger_rejects_overlapping_requests():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=20)
    ledger.begin(now=2, timeout_seconds=3)
    with pytest.raises(campaign.CampaignError):
        ledger.begin(now=3)


def test_request_ledger_rejects_request_deadline_overrun():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=20)
    ledger.begin(now=2, timeout_seconds=3)
    with pytest.raises(campaign.CampaignError):
        ledger.finish(1, outcome="completed", now=5.01, observed_tokens=1, transport_status=200)


def test_request_ledger_rejects_attempt_deadline_overrun_on_finish():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=10)
    with pytest.raises(campaign.CampaignError, match="request_timeout_exceeds_attempt_wall"):
        ledger.begin(now=8, timeout_seconds=5)


def _closed_completed_ledger():
    ledger = campaign.RequestLedger(max_requests=1, wall_seconds=30, token_stop_threshold=20)
    ledger.begin(now=0, timeout_seconds=3)
    ledger.finish(1, outcome="completed", now=1, observed_tokens=4, transport_status=200)
    ledger.close()
    return ledger


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ledger: ledger.requests.append({
            "index": 2, "started_at": 2, "timeout_seconds": 1, "request_kind": "ordinary",
            "native_stage": "unrelated", "run_id": None, "task_id": None,
            "budget_id": None, "request_sha256": "1" * 64,
            "finished": True, "finished_at": 3, "outcome": "completed", "observed_tokens": 1,
            "transport_status": 200, "terminal_reason": None,
        }),
        lambda ledger: ledger.requests[0].update({"started_at": -1}),
        lambda ledger: ledger.requests[0].update({"timeout_seconds": 601}),
        lambda ledger: ledger.requests[0].update({"observed_tokens": True}),
        lambda ledger: ledger.requests[0].update({"transport_status": 99}),
        lambda ledger: setattr(ledger, "known_observed_tokens", 99),
        lambda ledger: setattr(ledger, "usage_complete", False),
    ],
)
def test_request_ledger_audit_rejects_tampered_bounds_and_derived_values(mutate):
    ledger = _closed_completed_ledger()
    mutate(ledger)
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


def test_request_ledger_audit_rejects_time_overlap():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=30)
    ledger.begin(now=0, timeout_seconds=3)
    ledger.finish(1, outcome="completed", now=2, observed_tokens=1, transport_status=200)
    ledger.requests.append({
        "index": 2, "started_at": 1, "timeout_seconds": 1, "request_kind": "ordinary",
        "native_stage": "unrelated", "run_id": None, "task_id": None,
        "budget_id": None, "request_sha256": "1" * 64,
        "finished": True, "finished_at": 2, "outcome": "completed", "observed_tokens": 1,
        "transport_status": 200, "terminal_reason": None,
    })
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


def test_request_ledger_audit_rejects_rows_after_terminal_state():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=30)
    ledger.begin(now=0, timeout_seconds=3)
    ledger.finish(1, outcome="failed", now=1, observed_tokens=1, transport_status=503)
    ledger.requests.append({
        "index": 2, "started_at": 1, "timeout_seconds": 1, "request_kind": "ordinary",
        "native_stage": "unrelated", "run_id": None, "task_id": None,
        "budget_id": None, "request_sha256": "1" * 64,
        "finished": True, "finished_at": 2, "outcome": "completed", "observed_tokens": 1,
        "transport_status": 200, "terminal_reason": None,
    })
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


@pytest.mark.parametrize("outcome", ("failed", "unknown"))
def test_request_ledger_never_admits_a_request_after_terminal_exchange(outcome):
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=20)
    ledger.begin(now=0)
    ledger.finish(1, outcome=outcome, now=1, observed_tokens=1, transport_status=503)
    with pytest.raises(campaign.CampaignError):
        ledger.begin(now=2)


def _finish_preparation_request(ledger, index, stage, started_at):
    ledger.begin(
        now=started_at, request_kind="preparation", native_stage=stage,
    )
    ledger.finish(
        index, outcome="completed", now=started_at + 1,
        observed_tokens=1, transport_status=200,
    )


def test_request_backed_stages_require_all_native_requests_and_disjoint_bindings():
    ledger = campaign.RequestLedger()
    for index, stage in enumerate(("contract_compiler", "evaluator_compiler"), start=1):
        _finish_preparation_request(ledger, index, stage, (index - 1) * 2)
    ledger.bind_stage("preparation", [1, 2])
    with pytest.raises(campaign.CampaignError, match="preparation_phase_incomplete"):
        ledger.begin(
            now=4, native_stage="candidate_generation", run_id="run-001",
            task_id="task-001", budget_id="budget-001",
        )

    ledger = campaign.RequestLedger()
    for index, stage in enumerate(
        ("contract_compiler", "evaluator_compiler", "evaluator_auditor"), start=1,
    ):
        _finish_preparation_request(ledger, index, stage, (index - 1) * 2)
    ledger.begin(
        now=6, native_stage="candidate_generation", run_id="run-001",
        task_id="task-001", budget_id="budget-001",
    )
    ledger.finish(4, outcome="completed", now=7, observed_tokens=1, transport_status=200)
    ledger.bind_stage("preparation", [1, 2, 3])
    with pytest.raises(campaign.CampaignError, match="stage_binding_invalid"):
        ledger.bind_stage("candidate_generation", [3])
    ledger.bind_stage("candidate_generation", [4])


def test_candidate_generation_is_rejected_before_preparation_starts():
    ledger = campaign.RequestLedger()
    with pytest.raises(campaign.CampaignError, match="preparation_phase_incomplete"):
        ledger.begin(
            now=0, native_stage="candidate_generation", run_id="run-001",
            task_id="task-001", budget_id="budget-001",
        )


def test_candidate_generation_binding_accepts_multiple_turns_for_one_agent_request():
    ledger = campaign.RequestLedger()
    for index, native_stage in enumerate(
        ("contract_compiler", "evaluator_compiler", "evaluator_auditor"), start=1,
    ):
        ledger.begin(
            now=(index - 1) * 2, request_kind="preparation", native_stage=native_stage,
        )
        ledger.finish(index, outcome="completed", now=(index - 1) * 2 + 1)
    for index in (4, 5):
        ledger.begin(
            now=index * 2, native_stage="candidate_generation", run_id="run-001",
            task_id="task-001", budget_id="budget-001",
        )
        ledger.finish(index, outcome="completed", now=index * 2 + 1)
    ledger.bind_stage("preparation", [1, 2, 3])
    ledger.bind_stage("candidate_generation", [4, 5])
    ledger.close(now=11)
    assert ledger.stage_bindings["candidate_generation"] == (4, 5)
    assert ledger.audit()["ledger_finalized"] is True


def test_candidate_generation_binding_rejects_nonconsecutive_turns():
    ledger = campaign.RequestLedger()
    for index, native_stage in enumerate(
        ("contract_compiler", "evaluator_compiler", "evaluator_auditor"), start=1,
    ):
        _finish_preparation_request(ledger, index, native_stage, (index - 1) * 2)
    for index, native_stage in ((4, "candidate_generation"), (5, "unrelated"),
                                (6, "candidate_generation")):
        ledger.begin(
            now=index * 2, native_stage=native_stage,
            run_id="run-001" if native_stage == "candidate_generation" else None,
            task_id="task-001" if native_stage == "candidate_generation" else None,
            budget_id="budget-001" if native_stage == "candidate_generation" else None,
        )
        ledger.finish(index, outcome="completed", now=index * 2 + 1)
    ledger.bind_stage("preparation", [1, 2, 3])
    with pytest.raises(campaign.CampaignError, match="stage_binding_invalid"):
        ledger.bind_stage("candidate_generation", [4, 6])


def test_candidate_generation_binding_rejects_multiple_agent_request_identities():
    ledger = campaign.RequestLedger()
    for index, native_stage in enumerate(
        ("contract_compiler", "evaluator_compiler", "evaluator_auditor"), start=1,
    ):
        ledger.begin(
            now=(index - 1) * 2, request_kind="preparation", native_stage=native_stage,
        )
        ledger.finish(index, outcome="completed", now=(index - 1) * 2 + 1)
    for index, task_id in ((4, "task-001"), (5, "task-002")):
        ledger.begin(
            now=index * 2, native_stage="candidate_generation", run_id="run-001",
            task_id=task_id, budget_id="budget-001",
        )
        ledger.finish(index, outcome="completed", now=index * 2 + 1)
    with pytest.raises(campaign.CampaignError, match="stage_binding_invalid"):
        ledger.bind_stage("candidate_generation", [4, 5])


def test_total_wall_precedes_simultaneous_token_threshold():
    ledger = campaign.RequestLedger(wall_seconds=10, token_stop_threshold=5)
    ledger.begin(now=0, timeout_seconds=10)
    ledger.finish(
        1, outcome="completed", now=10, observed_tokens=5,
        transport_status=200,
    )
    assert ledger.closure_reason == "attempt_wall"
    assert ledger.terminal_outcome == "failed"
    assert ledger.audit()["ledger_finalized"] is False


def test_total_wall_precedes_simultaneous_max_request_limit():
    ledger = campaign.RequestLedger(max_requests=1, wall_seconds=10)
    ledger.begin(now=0, timeout_seconds=10)
    ledger.finish(
        1, outcome="completed", now=10, observed_tokens=1,
        transport_status=200,
    )
    assert ledger.closure_reason == "attempt_wall"


def test_total_wall_precedes_an_equal_request_deadline():
    ledger = campaign.RequestLedger(wall_seconds=10)
    ledger.begin(now=0, timeout_seconds=10)
    with pytest.raises(campaign.CampaignError, match="request_deadline_exceeded"):
        ledger.finish(1, outcome="completed", now=11, observed_tokens=1)
    assert ledger.requests[0]["terminal_reason"] == "attempt_wall"
    assert ledger.closure_reason == "attempt_wall"
    assert ledger.terminal_outcome == "failed"
    assert ledger.audit()["ledger_finalized"] is False


def test_repeated_close_with_different_time_rejects_anchor_rewrite():
    ledger = _closed_completed_ledger()
    with pytest.raises(campaign.CampaignError, match="closure_anchor_mismatch"):
        ledger.close(now=2)


def test_failed_first_preparation_request_can_be_receipted_before_cleanup():
    c = new_campaign()
    c.ledger.begin(
        now=0, request_kind="preparation", native_stage="contract_compiler",
    )
    c.ledger.finish(
        1, outcome="failed", now=1, observed_tokens=1,
        transport_status=503,
    )
    c.ledger.bind_stage("preparation", [1])
    c.preparation(
        evaluator_sha256="1" * 64, holdout_sha256="2" * 64,
        outcome="failed",
    )
    c.cleanup(
        verified=True, native_exit_code=1, process_exit_code=1,
    )
    result = c.public_result()
    assert result["stages"]["preparation"] == "failed"
    assert result["stages"]["cleanup"] == "succeeded"
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


def test_unrelated_single_request_cannot_stand_in_for_preparation_or_generation():
    ledger = campaign.RequestLedger()
    ledger.begin(now=0, native_stage="unrelated")
    ledger.finish(1, outcome="completed", now=1, observed_tokens=1, transport_status=200)
    with pytest.raises(campaign.CampaignError, match="stage_binding_invalid"):
        ledger.bind_stage("preparation", [1])
    with pytest.raises(campaign.CampaignError, match="stage_binding_invalid"):
        ledger.bind_stage("candidate_generation", [1])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_requests", 21),
        ("wall_seconds", 2401),
        ("token_stop_threshold", 160001),
        ("preparation_wall_seconds", 1861),
    ],
)
def test_campaign_rejects_runtime_ledger_policy_drift(field, value):
    c = complete_campaign()
    setattr(c.ledger, field, value)
    with pytest.raises(campaign.CampaignError, match="request_ledger_binding_mismatch"):
        c.public_result()


def test_final_request_followed_by_attempt_wall_expiry_is_not_successful():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=10)
    ledger.begin(now=0, timeout_seconds=3)
    ledger.finish(1, outcome="completed", now=1, observed_tokens=1, transport_status=200)
    ledger.close(now=10)
    assert ledger.audit()["ledger_finalized"] is False
    assert ledger.closure_reason == "attempt_wall"


def test_cumulative_preparation_wall_overrun_closes_the_slot():
    ledger = campaign.RequestLedger(wall_seconds=2400, preparation_wall_seconds=1860)
    _finish_preparation_request(ledger, 1, "contract_compiler", 0)
    _finish_preparation_request(ledger, 2, "evaluator_compiler", 900)
    ledger.begin(now=1800, request_kind="preparation", native_stage="evaluator_auditor")
    with pytest.raises(campaign.CampaignError, match="preparation_wall_exceeded"):
        ledger.finish(
            3, outcome="completed", now=1861, observed_tokens=1,
            transport_status=200,
        )
    assert ledger.closure_reason == "preparation_wall"
    assert ledger.closure_time == 1860
    assert ledger.audit()["ledger_finalized"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("observed_tokens", 1), ("transport_status", 504)],
)
def test_request_deadline_terminal_row_rejects_forged_observations(field, value):
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=30)
    ledger.begin(now=0, timeout_seconds=3)
    with pytest.raises(campaign.CampaignError, match="request_deadline_exceeded"):
        ledger.finish(1, outcome="completed", now=4)
    ledger.requests[0][field] = value
    if field == "observed_tokens":
        ledger.known_observed_tokens = value
        ledger.usage_complete = True
    ledger._closure_state_digest = ledger._closure_anchor_digest()
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


def test_ordinary_request_cannot_forge_preparation_wall_terminal_reason():
    ledger = campaign.RequestLedger(
        max_requests=2, wall_seconds=30, preparation_wall_seconds=5,
    )
    ledger.begin(now=0, timeout_seconds=10)
    ledger.finish(1, outcome="completed", now=5, observed_tokens=1, transport_status=200)
    ledger.close(now=5)
    ledger.requests[0].update({
        "outcome": "unknown", "observed_tokens": None, "transport_status": None,
        "terminal_reason": "preparation_wall",
    })
    ledger.known_observed_tokens = 0
    ledger.usage_complete = False
    ledger.closed_reason = "preparation_wall"
    ledger.terminal_outcome = "failed"
    ledger._closure_state_digest = ledger._closure_anchor_digest()
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("closed_at_index", 0),
        ("closed_at_time", 2),
        ("closed_reason", "request_failed"),
        ("terminal_outcome", "failed"),
    ],
)
def test_first_closure_anchor_rejects_summary_tampering(field, value):
    ledger = _closed_completed_ledger()
    setattr(ledger, field, value)
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


def test_repeated_close_cannot_repair_a_modified_first_closure():
    ledger = _closed_completed_ledger()
    ledger.closed_reason = "request_failed"
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.close()
