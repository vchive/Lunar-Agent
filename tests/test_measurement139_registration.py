"""Offline registration, launch preflight, and one-slot ledger fixtures."""
from __future__ import annotations

import copy

import pytest
from measurement139_support import campaign


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
            "finished": True, "finished_at": 3, "outcome": "completed", "observed_tokens": 1,
            "transport_status": 200,
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
        "finished": True, "finished_at": 2, "outcome": "completed", "observed_tokens": 1,
        "transport_status": 200,
    })
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        ledger.audit()


def test_request_ledger_audit_rejects_rows_after_terminal_state():
    ledger = campaign.RequestLedger(max_requests=2, wall_seconds=30)
    ledger.begin(now=0, timeout_seconds=3)
    ledger.finish(1, outcome="failed", now=1, observed_tokens=1, transport_status=503)
    ledger.requests.append({
        "index": 2, "started_at": 1, "timeout_seconds": 1, "request_kind": "ordinary",
        "finished": True, "finished_at": 2, "outcome": "completed", "observed_tokens": 1,
        "transport_status": 200,
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
