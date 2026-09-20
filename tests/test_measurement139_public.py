"""Public projection, audit tamper detection, and historical-boundary fixtures."""
from __future__ import annotations

import hashlib

import pytest
from measurement139_support import analysis, campaign, case, complete_campaign, new_campaign


def _rehash_receipts(c):
    for row in c.receipts:
        row["receipt_sha256"] = campaign.digest_json({key: value for key, value in row.items() if key != "receipt_sha256"})


def _rebuild_receipt_chain(c):
    chain = campaign.digest_json({"schema_version": campaign.SCHEMA_VERSION, **c.identity})
    delivery_receipt_sha256 = None
    for row in c.receipts:
        if row["stage"] == "holdouts" and delivery_receipt_sha256 is not None:
            row["delivery_receipt_sha256"] = delivery_receipt_sha256
        row["previous_receipt_sha256"] = chain
        row["stage_run_sha256"] = campaign.digest_json({
            "stage": row["stage"], "outcome": row["outcome"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
            "payload": {
                key: row[key] for key in campaign._STAGE_PAYLOAD_KEYS[row["stage"]]
            },
        })
        row["receipt_sha256"] = campaign.digest_json({
            key: value for key, value in row.items() if key != "receipt_sha256"
        })
        if row["stage"] == "parent_delivery":
            delivery_receipt_sha256 = row["receipt_sha256"]
        chain = campaign.digest_json({"previous": chain, "receipt": row["receipt_sha256"]})
    c._receipt_chain_sha256 = chain


def test_public_projection_is_allow_listed_and_redacts_private_evidence():
    c = complete_campaign()
    result = analysis.public_result(c)
    analysis.assert_public_safe(result)
    assert set(result) == {
        "registration_id", "campaign_id", "attempt_id", "planned_attempts", "attempts",
        "provider_requests", "usage", "transport", "stages", "completed_candidate_count", "holdouts", "score",
        "primary_success", "joint_success", "receipt_digests",
    }
    assert result["score"] == 3
    serialized = repr(result).lower()
    assert "prompt" not in serialized and "response" not in serialized and "credential" not in serialized
    assert "https://" not in serialized


def test_public_result_does_not_trust_producer_claimed_score():
    c = complete_campaign()
    score = next(row for row in c.receipts if row["stage"] == "independent_scoring")
    assert "producer_score" not in score
    assert c.public_result()["score"] == 3


def test_audit_is_read_only_and_detects_digest_or_identity_tampering():
    c = complete_campaign()
    before = [dict(row) for row in c.receipts]
    assert analysis.audit(c)["one_attempt"] is True
    assert c.receipts == before
    c.receipts[1]["candidate_id"] = "candidate-999"
    with pytest.raises(campaign.CampaignError, match="receipt_digest_mismatch"):
        analysis.audit(c)
    c = complete_campaign()
    c.receipts[1]["receipt_sha256"] = campaign.digest_json({k: v for k, v in c.receipts[1].items() if k != "receipt_sha256"})
    c.receipts[1]["registration_id"] = "registration-other"
    with pytest.raises(campaign.CampaignError, match="receipt_identity_mismatch"):
        analysis.audit(c)


def test_historical_ids_and_bytes_are_not_part_of_new_manifest():
    manifest = campaign.default_manifest()
    assert manifest["registration_id"] not in {"acceptance131", "acceptance134"}
    assert manifest["campaign_id"] not in {"acceptance131", "acceptance134"}
    assert manifest["input_sha256"] == hashlib.sha256(case.INPUT_BYTES).hexdigest()
    assert manifest["task_sha256"] == hashlib.sha256(case.TASK_BYTES).hexdigest()


def test_unknown_usage_and_transport_remain_unknown_in_bounded_ledger():
    c = new_campaign()
    c.ledger.begin(now=0)
    c.ledger.finish(1, outcome="unknown", now=1, observed_tokens=None, transport_status=None)
    result = c.public_result()
    assert result["provider_requests"] == 1
    assert c.ledger.snapshot()["observed_tokens"] is None
    assert c.ledger.snapshot()["pending_requests"] == []


def test_success_requires_a_closed_nonempty_ledger():
    c = complete_campaign()
    c.ledger = campaign.RequestLedger()
    result = c.public_result()
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


def test_success_rejects_a_ledger_with_pending_requests():
    c = complete_campaign()
    c.ledger = campaign.RequestLedger()
    c.ledger.begin(now=0)
    result = c.public_result()
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


def test_unknown_request_usage_stays_explicit_in_the_public_projection():
    c = complete_campaign()
    c.ledger = campaign.RequestLedger()
    c.ledger.begin(now=0)
    c.ledger.finish(1, outcome="completed", now=1, observed_tokens=None, transport_status=200)
    c.ledger.close()
    result = c.public_result()
    assert result["usage"] == {"observed_tokens": None, "complete": False}
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


def test_unknown_usage_does_not_fail_success_when_ledger_bindings_are_intact():
    c = complete_campaign(observed_tokens=None)
    result = c.public_result()
    assert result["usage"] == {"observed_tokens": None, "complete": False}
    assert result["primary_success"] == "1/1"
    assert result["joint_success"] == "1/1"


def test_extra_unbound_completed_request_cannot_support_success():
    result = complete_campaign(extra_unbound_request=True).public_result()
    assert result["provider_requests"] == 5
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


@pytest.mark.parametrize("field", ("run_id", "task_id", "budget_id"))
def test_generation_receipt_identity_must_match_the_bound_request(field):
    c = complete_campaign()
    generated = next(row for row in c.receipts if row["stage"] == "candidate_generation")
    generated[field] = "other-001"
    _rebuild_receipt_chain(c)
    with pytest.raises(campaign.CampaignError, match="candidate_receipt_invalid"):
        c.audit()


@pytest.mark.parametrize("field", ("native_exit_code", "process_exit_code"))
def test_nonzero_cleanup_exit_prevents_joint_success(field):
    c = complete_campaign()
    cleanup = next(row for row in c.receipts if row["stage"] == "cleanup")
    cleanup[field] = 1
    _rebuild_receipt_chain(c)
    result = c.public_result()
    assert result["primary_success"] == "1/1"
    assert result["joint_success"] == "0/1"


def test_cleanup_binds_the_whole_attempt_completion_anchor():
    c = complete_campaign()
    cleanup = next(row for row in c.receipts if row["stage"] == "cleanup")
    assert c.attempt_finished_at == cleanup["finished_at"]
    assert c.attempt_finished_at > c.ledger.provider_finished_at
    c.attempt_finished_at += 1
    with pytest.raises(campaign.CampaignError, match="attempt_completion_anchor_mismatch"):
        c.audit()


def test_local_stage_after_total_wall_is_rejected_even_with_rehashed_receipts():
    c = complete_campaign()
    execution = next(row for row in c.receipts if row["stage"] == "candidate_execution")
    execution["started_at"] = 2401
    execution["finished_at"] = 2402
    _rebuild_receipt_chain(c)
    with pytest.raises(campaign.CampaignError, match="receipt_time_invalid"):
        c.audit()


def test_preparation_receipt_cannot_omit_auditor_after_full_rehash():
    c = complete_campaign()
    preparation = next(row for row in c.receipts if row["stage"] == "preparation")
    preparation["request_count"] = 2
    preparation["request_ledger_sha256"] = c.ledger.prefix_digest(2)
    _rebuild_receipt_chain(c)
    with pytest.raises(campaign.CampaignError, match="receipt_request_binding_mismatch"):
        c.audit()


def test_public_result_rejects_a_tampered_successful_ledger():
    c = complete_campaign()
    c.ledger.usage_complete = False
    with pytest.raises(campaign.CampaignError, match="request_ledger_invalid"):
        c.public_result()


def test_public_result_rejects_manifest_tampering_even_when_receipts_are_intact():
    c = complete_campaign()
    c.manifest["input_sha256"] = "9" * 64
    with pytest.raises(campaign.CampaignError, match="manifest_digest_mismatch"):
        c.public_result()


def test_public_result_rejects_forged_campaign_identity_after_full_rehash():
    c = complete_campaign()
    forged = {
        "registration_id": "registration-forged",
        "campaign_id": "campaign-forged",
        "attempt_id": "attempt-forged",
    }
    c._identity = forged
    for row in c.receipts:
        row.update(forged)
    _rebuild_receipt_chain(c)
    with pytest.raises(campaign.CampaignError, match="manifest_identity_mismatch"):
        c.public_result()


def test_unknown_holdout_cannot_produce_joint_success():
    c = complete_campaign(holdout_outcome="unknown")
    result = c.public_result()
    assert result["primary_success"] == "1/1"
    assert result["joint_success"] == "0/1"


def test_audit_rejects_rehashed_out_of_order_holdout_receipt():
    c = complete_campaign()
    holdout = c.receipts.pop(6)
    c.receipts.insert(1, holdout)
    _rehash_receipts(c)
    with pytest.raises(campaign.CampaignError):
        analysis.audit(c)


def test_audit_rejects_rehashed_registered_input_link_tampering():
    c = complete_campaign()
    execution = next(row for row in c.receipts if row["stage"] == "candidate_execution")
    delivery = next(row for row in c.receipts if row["stage"] == "parent_delivery")
    execution["input_sha256"] = "9" * 64
    delivery["input_sha256"] = "9" * 64
    _rehash_receipts(c)
    with pytest.raises(campaign.CampaignError):
        analysis.audit(c)


def test_audit_rejects_rehashed_delivery_evidence_link_tampering():
    c = complete_campaign()
    holdout = next(row for row in c.receipts if row["stage"] == "holdouts")
    holdout["delivery_receipt_sha256"] = "9" * 64
    _rehash_receipts(c)
    with pytest.raises(campaign.CampaignError):
        analysis.audit(c)
