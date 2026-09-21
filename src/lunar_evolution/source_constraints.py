"""Pure, reproducible checks of declared source structure, without executing source code."""
from __future__ import annotations

from .algorithm import MAX_ERROR_INFO, AlgorithmProblemContract, EvaluationReport
from .candidate_bundle import CandidateSourceBundle, validate_candidate_source_bundle
from .candidate_evaluation_spec import canonical_json, strict_json
from .candidate_workspace_plan import candidate_file_table_sha256

SOURCE_CHECK_PROTOCOL = "lunar-source-checks-v1"
MAX_SOURCE_CHECK_BYTES = 256 * 1024


def source_constraints(contract):
    """Return supported hard source checks; never silently admit other source requirements."""
    return tuple(item for item in contract.hard_constraints
                 if item.verification_scope == "source" and item.source_check is not None)


def unsupported_source_constraints(contract, *, allow_source_checks=True):
    verified = AlgorithmProblemContract.from_dict(contract.to_dict())
    supported = {item.id for item in source_constraints(verified)} if allow_source_checks else set()
    return tuple((item.id, item.verification_scope)
                 for item in (*verified.hard_constraints, *verified.soft_constraints)
                 if item.verification_scope in {"source", "execution"} and item.id not in supported)


def validate_source_capabilities(contract):
    if unsupported_source_constraints(contract):
        raise ValueError("source_check_unsupported_constraints")


def source_check_evidence(contract, bundle):
    contract = AlgorithmProblemContract.from_dict(contract.to_dict())
    validate_source_capabilities(contract)
    bundle = validate_candidate_source_bundle(bundle)
    constraints = source_constraints(contract)
    if not constraints or bundle.contract_sha256 != contract.digest():
        raise ValueError("source_check_identity_mismatch")
    observed = sum(item.path.endswith(".py") for item in bundle.files)
    checks = [{"id": item.id, "kind": item.source_check.kind, "minimum": item.source_check.minimum,
               "observed": observed, "passed": observed >= item.source_check.minimum}
              for item in constraints]
    return {
        "protocol": SOURCE_CHECK_PROTOCOL, "schema_version": "1",
        "contract_sha256": contract.digest(), "bundle_sha256": bundle.digest(),
        "source_file_table_sha256": candidate_file_table_sha256(bundle),
        "bundle": bundle.to_dict(), "checks": checks,
        "validity": all(check["passed"] for check in checks),
    }


def validate_source_check_evidence(value, contract, *, bundle_sha256=None, source_file_table_sha256=None):
    """Recompute all claims from the pinned full bundle; no filesystem or runtime calls."""
    if not isinstance(value, dict):
        raise TypeError("source_check_invalid")
    bundle = CandidateSourceBundle.from_dict(value.get("bundle"))
    expected = source_check_evidence(contract, bundle)
    # Canonical bytes also distinguish boolean claims from integer lookalikes.
    if (canonical_json(value, maximum=MAX_SOURCE_CHECK_BYTES) != canonical_json(expected, maximum=MAX_SOURCE_CHECK_BYTES)
            or (bundle_sha256 is not None and bundle.digest() != bundle_sha256)
            or (source_file_table_sha256 is not None
                and expected["source_file_table_sha256"] != source_file_table_sha256)):
        raise ValueError("source_check_identity_mismatch")
    return expected


def source_failure_report(evaluator_id, evidence):
    """A deterministic invalid report cannot be overridden by a model or output score."""
    failed = [item for item in evidence["checks"] if not item["passed"]]
    # Complete failures remain in the bound evidence; reports have a smaller error-count cap.
    return EvaluationReport(
        "1", evaluator_id, 0, 0.0, {}, tuple(
            {"code": item["id"], "message": "Declared minimum Python source-file count was not met."}
            for item in failed[:MAX_ERROR_INFO]
        ),
    )


def parse_source_check_evidence(content, contract, *, bundle_sha256, source_file_table_sha256=None):
    value = strict_json(content, maximum=MAX_SOURCE_CHECK_BYTES)
    expected = validate_source_check_evidence(
        value, contract, bundle_sha256=bundle_sha256,
        source_file_table_sha256=source_file_table_sha256,
    )
    if canonical_json(expected, maximum=MAX_SOURCE_CHECK_BYTES) != content:
        raise ValueError("source_check_not_canonical")
    return expected
