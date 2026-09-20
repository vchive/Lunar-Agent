"""Import helper for the hyphenated Feature 139 campaign directory."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "feature139_measurement"
PACKAGE_ROOT = ROOT / "specs/139-real-multifile-closure/measurement"


def load_feature139():
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE,
            PACKAGE_ROOT / "__init__.py",
            submodule_search_locations=[str(PACKAGE_ROOT)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return sys.modules[PACKAGE]


feature139 = load_feature139()
campaign = sys.modules[f"{PACKAGE}.campaign"]
case = sys.modules[f"{PACKAGE}.case"]
analysis_spec = importlib.util.find_spec(f"{PACKAGE}.analysis")
assert analysis_spec is not None and analysis_spec.loader is not None
analysis = importlib.util.module_from_spec(analysis_spec)
sys.modules[f"{PACKAGE}.analysis"] = analysis
analysis_spec.loader.exec_module(analysis)


def new_campaign():
    return campaign.ClosureCampaign(
        campaign.default_manifest(), registration_head="offline-registration-pin",
        registration_origin="offline-registration-pin",
    )


def complete_campaign(*, holdout_outcome="succeeded", observed_tokens=7,
                      extra_unbound_request=False, generation_turns=1):
    c = new_campaign()
    for index, native_stage in enumerate(
        ("contract_compiler", "evaluator_compiler", "evaluator_auditor"), start=1,
    ):
        started_at = (index - 1) * 2
        c.ledger.begin(
            now=started_at, request_kind="preparation", native_stage=native_stage,
        )
        c.ledger.finish(
            index, outcome="completed", now=started_at + 1,
            observed_tokens=1, transport_status=200,
        )
    generation_indices = []
    for offset in range(generation_turns):
        index = 4 + offset
        started_at = 6 + offset * 2
        c.ledger.begin(
            now=started_at, native_stage="candidate_generation", run_id="run-001",
            task_id="task-001", budget_id="budget-001",
        )
        c.ledger.finish(
            index, outcome="completed", now=started_at + 1,
            observed_tokens=observed_tokens if offset == generation_turns - 1 else 1,
            transport_status=200,
        )
        generation_indices.append(index)
    c.ledger.bind_stage("preparation", [1, 2, 3])
    c.ledger.bind_stage("candidate_generation", generation_indices)
    provider_finished_at = 5 + generation_turns * 2
    if extra_unbound_request:
        unrelated_index = 4 + generation_turns
        c.ledger.begin(now=provider_finished_at + 1, native_stage="unrelated")
        c.ledger.finish(
            unrelated_index, outcome="completed", now=provider_finished_at + 2,
            observed_tokens=1,
            transport_status=200,
        )
    c.ledger.close(now=provider_finished_at + 2 if extra_unbound_request else provider_finished_at)
    local_start = provider_finished_at + 3 if extra_unbound_request else provider_finished_at + 1
    c.preparation(
        evaluator_sha256="1" * 64, holdout_sha256="2" * 64,
        started_at=0, finished_at=5,
    )
    c.candidate_generation({
        "candidate_id": "candidate-001",
        "diagnostic": "completed",
        "files": case.synthetic_source(),
    }, started_at=6, finished_at=provider_finished_at)
    c.candidate_execution(
        candidate_id="candidate-001",
        execution_id="execution-001",
        source_sha256=campaign.digest_json(case.synthetic_source()),
        input_sha256=case.expected_input_digest(),
        output_sha256=campaign.digest_bytes(case.synthetic_output()),
        exit_code=0,
        started_at=local_start,
        finished_at=local_start + 1,
    )
    c.independent_scoring(
        candidate_id="candidate-001",
        execution_id="execution-001",
        evaluation_id="evaluation-001",
        valid=True,
        score=3,
        report_sha256="3" * 64,
        producer_score=999999,
        started_at=local_start + 2,
        finished_at=local_start + 3,
    )
    c.selection(
        candidate_id="candidate-001", execution_id="execution-001",
        evaluation_id="evaluation-001", started_at=local_start + 4,
        finished_at=local_start + 5,
    )
    c.parent_delivery(
        candidate_id="candidate-001",
        execution_id="execution-001",
        evaluation_id="evaluation-001",
        source_sha256=campaign.digest_json(case.synthetic_source()),
        input_sha256=case.expected_input_digest(),
        output_sha256=campaign.digest_bytes(case.synthetic_output()),
        evidence_sha256="4" * 64,
        started_at=local_start + 6,
        finished_at=local_start + 7,
    )
    c.holdouts(
        [
            {"index": row["index"], "actual_value": row["expected_value"],
             "elapsed_seconds": 0.1}
            for row in case.default_holdouts()
        ],
        outcome=holdout_outcome, started_at=local_start + 8,
        finished_at=local_start + 9,
    )
    c.cleanup(
        verified=True, native_exit_code=0, process_exit_code=0,
        started_at=local_start + 9, finished_at=local_start + 10,
    )
    return c
