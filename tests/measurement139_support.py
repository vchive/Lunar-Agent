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


def complete_campaign():
    c = new_campaign()
    c.ledger.begin(now=0)
    c.ledger.finish(1, outcome="completed", now=1, observed_tokens=7, transport_status=200)
    c.ledger.close()
    c.preparation(evaluator_sha256="1" * 64, holdout_sha256="2" * 64)
    c.candidate_generation({
        "candidate_id": "candidate-001",
        "diagnostic": "completed",
        "files": case.synthetic_source(),
    })
    c.candidate_execution(
        candidate_id="candidate-001",
        execution_id="execution-001",
        source_sha256=campaign.digest_json(case.synthetic_source()),
        input_sha256=case.expected_input_digest(),
        output_sha256=campaign.digest_bytes(case.synthetic_output()),
        exit_code=0,
    )
    c.independent_scoring(
        candidate_id="candidate-001",
        execution_id="execution-001",
        evaluation_id="evaluation-001",
        valid=True,
        score=3,
        report_sha256="3" * 64,
        producer_score=999999,
    )
    c.selection(candidate_id="candidate-001", execution_id="execution-001", evaluation_id="evaluation-001")
    c.parent_delivery(
        candidate_id="candidate-001",
        execution_id="execution-001",
        evaluation_id="evaluation-001",
        source_sha256=campaign.digest_json(case.synthetic_source()),
        input_sha256=case.expected_input_digest(),
        output_sha256=campaign.digest_bytes(case.synthetic_output()),
        evidence_sha256="4" * 64,
    )
    c.holdouts([{"index": index, "matched": True} for index in range(1, 9)])
    c.cleanup(verified=True)
    return c
