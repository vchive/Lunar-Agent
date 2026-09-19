"""Provider-free six-stage receipts and first-failure fixtures."""
from __future__ import annotations

import pytest
from measurement139_support import campaign, case, complete_campaign, new_campaign


def test_parser_accepts_only_completed_nonempty_source_bundle():
    valid = {"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()}
    parsed = campaign.parse_candidate(valid)
    assert parsed["candidate_id"] == "candidate-001"
    assert parsed["file_count"] == 2
    for invalid in (
        {**valid, "diagnostic": "timeout"},
        {**valid, "files": {}},
        {**valid, "files": {"../escape.py": "x"}},
        {**valid, "files": {"solve/main.py": ""}},
    ):
        with pytest.raises(campaign.CampaignError):
            campaign.parse_candidate(invalid)


def test_complete_stage_chain_binds_all_identities_and_has_one_denominator():
    c = complete_campaign()
    audit = c.audit()
    assert audit == {
        "receipt_count": 8,
        "stages": [
            "preparation", "candidate_generation", "candidate_execution",
            "independent_scoring", "selection", "parent_delivery", "holdouts", "cleanup",
        ],
        "one_attempt": True,
        "ledger_finalized": True,
        "usage_complete": True,
    }
    result = c.public_result()
    assert result["primary_success"] == "1/1"
    assert result["joint_success"] == "1/1"
    assert result["completed_candidate_count"] == 1


def test_stage_order_rejects_missing_receipt_and_never_infers_later_success():
    c = new_campaign()
    with pytest.raises(campaign.CampaignError, match="stage_out_of_order"):
        c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64, outcome="failed")
    with pytest.raises(campaign.CampaignError, match="chain_stopped_after_failure"):
        c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    c.cleanup(verified=True)
    result = c.public_result()
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"
    assert result["stages"]["candidate_generation"] == "absent"


def test_unknown_preparation_is_terminal_and_cleanup_is_observable():
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64, outcome="unknown")
    c.cleanup(verified=False, outcome="unknown")
    result = c.public_result()
    assert result["stages"]["preparation"] == "unknown"
    assert result["stages"]["cleanup"] == "unknown"
    assert result["primary_success"] == "0/1"
    assert result["joint_success"] == "0/1"


def test_candidate_budget_or_empty_response_cannot_become_completed_candidate():
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "budget_exhausted", "files": {}}, outcome="failed")
    c.cleanup(verified=True)
    assert c.public_result()["completed_candidate_count"] == 0
    assert c.public_result()["primary_success"] == "0/1"


def test_identity_and_integrity_mismatch_cannot_cross_stage_boundary():
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    source_sha = campaign.digest_json(case.synthetic_source())
    c.candidate_execution(candidate_id="candidate-001", execution_id="execution-001", source_sha256=source_sha,
                          input_sha256=case.expected_input_digest(), output_sha256=campaign.digest_bytes(case.synthetic_output()), exit_code=0)
    with pytest.raises(campaign.CampaignError, match="evaluation_identity_mismatch"):
        c.independent_scoring(candidate_id="candidate-other", execution_id="execution-001", evaluation_id="evaluation-001",
                              valid=True, score=3, report_sha256="3" * 64)
    c.independent_scoring(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001",
                          valid=True, score=3, report_sha256="3" * 64, producer_score=999)
    c.selection(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001")
    with pytest.raises(campaign.CampaignError, match="delivery_integrity_mismatch"):
        c.parent_delivery(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001",
                          source_sha256="9" * 64, input_sha256=case.expected_input_digest(),
                          output_sha256=campaign.digest_bytes(case.synthetic_output()), evidence_sha256="4" * 64)


def test_execution_input_digest_must_match_the_registered_manifest():
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    with pytest.raises(campaign.CampaignError):
        c.candidate_execution(
            candidate_id="candidate-001",
            execution_id="execution-001",
            source_sha256=campaign.digest_json(case.synthetic_source()),
            input_sha256="9" * 64,
            output_sha256=campaign.digest_bytes(case.synthetic_output()),
            exit_code=0,
        )


def test_invalid_score_cannot_be_selected_or_delivered():
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    c.candidate_execution(candidate_id="candidate-001", execution_id="execution-001", source_sha256=campaign.digest_json(case.synthetic_source()),
                          input_sha256=case.expected_input_digest(), output_sha256=campaign.digest_bytes(case.synthetic_output()), exit_code=0)
    c.independent_scoring(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001",
                          valid=False, score=None, report_sha256="3" * 64)
    with pytest.raises(campaign.CampaignError, match="invalid_candidate_cannot_be_selected"):
        c.selection(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001")
    c.cleanup(verified=True)
    assert c.public_result()["primary_success"] == "0/1"


@pytest.mark.parametrize("score", (None, float("nan"), float("inf"), float("-inf")))
def test_valid_independent_score_must_be_finite_and_numeric(score):
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({"candidate_id": "candidate-001", "diagnostic": "completed", "files": case.synthetic_source()})
    c.candidate_execution(
        candidate_id="candidate-001",
        execution_id="execution-001",
        source_sha256=campaign.digest_json(case.synthetic_source()),
        input_sha256=case.expected_input_digest(),
        output_sha256=campaign.digest_bytes(case.synthetic_output()),
        exit_code=0,
    )
    with pytest.raises(campaign.CampaignError):
        c.independent_scoring(
            candidate_id="candidate-001",
            execution_id="execution-001",
            evaluation_id="evaluation-001",
            valid=True,
            score=score,
            report_sha256="3" * 64,
        )


def test_holdout_and_cleanup_receipts_are_gated_and_bounded():
    c = complete_campaign()
    # The successful fixture has already consumed both terminal observations.
    with pytest.raises(campaign.CampaignError, match="duplicate_stage"):
        c.cleanup(verified=True)
    c = new_campaign()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    with pytest.raises(campaign.CampaignError, match="holdouts_before_delivery"):
        c.holdouts([{"index": index, "matched": True} for index in range(1, 9)])
