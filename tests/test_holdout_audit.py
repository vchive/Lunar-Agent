from __future__ import annotations

import copy
import hashlib
import json

import pytest

import lunar_evolution
import lunar_evolution.holdout_audit as holdout_module
from lunar_evolution.acceptance_observer import AcceptanceObservationError
from lunar_evolution.holdout_audit import (
    HoldoutAuditError,
    audit_holdout_receipts,
    build_holdout_declaration,
    build_holdout_receipt,
    parse_holdout_declaration,
    parse_holdout_receipt,
)


def declaration():
    return build_holdout_declaration({
        "schema_version": "1", "manifest_sha256": "a" * 64,
        "evaluator_sha256": "b" * 64, "evaluator_version": "eval-v1",
        "candidate_id": "candidate-1", "execution_sha256": "c" * 64,
        "holdouts": [
            {"holdout_id": f"h{i}", "ordinal": i, "input_sha256": f"{i+1:064x}",
             "expected_output_sha256": f"{i+11:064x}", "max_duration_ms": 5000}
            for i in range(8)
        ],
    })


def receipt(d, i, *, actual=None, outcome="passed", native=0, process=0, cleanup="verified", duration=1):
    data = {
        "schema_version": "1", "manifest_sha256": d["manifest_sha256"],
        "declaration_sha256": d["declaration_sha256"],
        "evaluator_sha256": d["evaluator_sha256"], "evaluator_version": d["evaluator_version"],
        "candidate_id": d["candidate_id"], "execution_sha256": d["execution_sha256"],
        "holdout_id": f"h{i}", "ordinal": i, "input_sha256": d["holdouts"][i]["input_sha256"],
        "expected_output_sha256": d["holdouts"][i]["expected_output_sha256"],
        "actual_output_sha256": actual or d["holdouts"][i]["expected_output_sha256"],
        "native_exit_code": native, "process_exit_code": process, "cleanup": cleanup,
        "duration_ms": duration, "outcome": outcome,
    }
    return build_holdout_receipt(data, declaration=d)


def snapshots(d):
    out = {}
    for i, h in enumerate(d["holdouts"]):
        # receipt digests need correspond to retained bytes
        inp, exp, act = bytes([i]), bytes([i + 10]), bytes([i + 10])
        h["input_sha256"] = hashlib.sha256(inp).hexdigest()
        h["expected_output_sha256"] = hashlib.sha256(exp).hexdigest()
        out[h["holdout_id"]] = {"input": inp, "expected_output": exp, "actual_output": act}
    d.pop("declaration_sha256")
    d.update(build_holdout_declaration(d))
    return out


def test_canonical_declaration_and_receipt_round_trip():
    d = declaration()
    assert parse_holdout_declaration(d) == d
    r = receipt(d, 0)
    text = json.dumps(r, sort_keys=True, separators=(",", ":"))
    assert parse_holdout_receipt(text, declaration=d) == r


def test_duplicate_and_noncanonical_json_rejected():
    d = declaration()
    raw = json.dumps(d, sort_keys=True, separators=(",", ":"))
    with pytest.raises(HoldoutAuditError, match="duplicate"):
        parse_holdout_declaration(raw[:-1] + ',"schema_version":"1"}')
    with pytest.raises(HoldoutAuditError, match="noncanonical"):
        parse_holdout_declaration(json.dumps(d, indent=2))


def test_all_eight_passes_make_joint_eligible_only_with_primary():
    d = declaration()
    snap = snapshots(d)
    rs = [receipt(d, i) for i in range(8)]
    report = audit_holdout_receipts(d, rs, retained_snapshots=snap, primary_eligible=True)
    assert report["holdout_counts"] == {"passed": 8, "failed": 0, "unknown": 0, "missing": 0}
    assert report["joint_eligible"] is True
    assert report["provider_called_during_audit"] is False


def test_missing_and_bad_receipts_do_not_join():
    d = declaration()
    snap = snapshots(d)
    rs = [receipt(d, i) for i in range(7)]
    rs[1] = receipt(d, 1, native=1)
    report = audit_holdout_receipts(d, rs, retained_snapshots=snap, primary_eligible=True)
    assert report["holdout_counts"]["missing"] == 1
    assert report["holdout_counts"]["failed"] == 1
    assert report["joint_eligible"] is False


@pytest.mark.parametrize("field", ["manifest_sha256", "expected_output_sha256", "receipt_sha256"])
def test_tamper_rejected(field):
    d = declaration()
    r = receipt(d, 0)
    r[field] = "f" * 64
    with pytest.raises(HoldoutAuditError):
        parse_holdout_receipt(r, declaration=d)


def test_digest_and_snapshot_mismatch_fail_closed():
    d = declaration()
    snap = snapshots(d)
    r = receipt(d, 0, actual="d" * 64)
    report = audit_holdout_receipts(d, [r], retained_snapshots=snap)
    assert report["holdout_counts"]["failed"] == 1
    assert report["first_problem"]["reason"] == "snapshot_digest_mismatch"


def test_limits_and_identity_are_bounded():
    d = declaration()
    with pytest.raises(HoldoutAuditError, match="holdout_count"):
        build_holdout_declaration({**{k: v for k, v in d.items() if k != "declaration_sha256"}, "holdouts": d["holdouts"][:7]})
    with pytest.raises(HoldoutAuditError, match="duration"):
        receipt(d, 0, duration=5001)
    forged = receipt(d, 0)
    forged["candidate_id"] = "other"
    with pytest.raises(HoldoutAuditError, match="identity"):
        build_holdout_receipt(forged, declaration=d)


def test_audit_does_not_mutate_inputs():
    d = declaration()
    snap = snapshots(d)
    rs = [receipt(d, i) for i in range(8)]
    before = copy.deepcopy((d, rs, snap))
    audit_holdout_receipts(d, rs, retained_snapshots=snap)
    assert (d, rs, snap) == before


@pytest.mark.parametrize("mutation", [
    lambda d: d["holdouts"][1].update(holdout_id="h0"),
    lambda d: d["holdouts"][1].update(ordinal=0),
    lambda d: d["holdouts"][0].update(max_duration_ms=5001),
    lambda d: d["holdouts"][0].update(max_duration_ms=True),
    lambda d: d.update(prompt="private"),
    lambda d: d.update(evaluator_version="https://private.invalid"),
])
def test_declaration_rejects_invalid_or_private_fields(mutation):
    d = declaration()
    d.pop("declaration_sha256")
    mutation(d)
    with pytest.raises(HoldoutAuditError):
        build_holdout_declaration(d)


def test_declaration_digest_prevents_retained_edits():
    d = declaration()
    d["holdouts"][0]["input_sha256"] = "f" * 64
    with pytest.raises(HoldoutAuditError, match="declaration_digest_mismatch"):
        parse_holdout_declaration(d)


@pytest.mark.parametrize("damage", ["duplicate", "out_of_order", "extra"])
def test_receipts_reject_duplicate_extra_and_out_of_order(damage):
    d = declaration()
    rs = [receipt(d, i) for i in range(8)]
    if damage == "duplicate":
        rs[1] = rs[0]
    elif damage == "out_of_order":
        rs[0], rs[1] = rs[1], rs[0]
    else:
        rs.append(rs[0])
    with pytest.raises(HoldoutAuditError):
        audit_holdout_receipts(d, rs)


@pytest.mark.parametrize("field,value", [
    ("manifest_sha256", "f" * 64),
    ("declaration_sha256", "f" * 64),
    ("evaluator_sha256", "f" * 64),
    ("evaluator_version", "other-v1"),
    ("candidate_id", "other"),
    ("execution_sha256", "f" * 64),
    ("input_sha256", "f" * 64),
    ("expected_output_sha256", "f" * 64),
    ("holdout_id", "h-undeclared"),
    ("ordinal", 1),
])
def test_forged_self_consistent_receipt_cannot_change_bound_identity(field, value):
    d = declaration()
    r = receipt(d, 0)
    r[field] = value
    r = build_holdout_receipt(r)
    with pytest.raises(HoldoutAuditError):
        audit_holdout_receipts(d, [r])


@pytest.mark.parametrize("change,status,reason", [
    ({"native": None}, "unknown", "exit_unknown"),
    ({"process": None}, "unknown", "exit_unknown"),
    ({"native": -9}, "failed", "exit_failed"),
    ({"process": 1}, "failed", "exit_failed"),
    ({"cleanup": "unknown"}, "unknown", "cleanup_unknown"),
    ({"cleanup": "failed"}, "failed", "cleanup_failed"),
    ({"outcome": "unknown"}, "unknown", "outcome_unknown"),
    ({"outcome": "failed"}, "failed", "outcome_failed"),
    ({"native": None, "cleanup": "failed"}, "failed", "cleanup_failed"),
])
def test_unknown_and_failed_observations_are_never_passes(change, status, reason):
    d = declaration()
    snap = snapshots(d)
    report = audit_holdout_receipts(d, [receipt(d, 0, **change)], retained_snapshots=snap,
                                    primary_eligible=True)
    assert report["holdout_counts"][status] == 1
    assert report["first_problem"]["reason"] == reason
    assert report["joint_eligible"] is False


def test_no_snapshot_and_no_primary_do_not_establish_joint():
    d = declaration()
    snap = snapshots(d)
    rs = [receipt(d, i) for i in range(8)]
    report = audit_holdout_receipts(d, rs, primary_eligible=True)
    assert report["holdout_counts"]["unknown"] == 8
    assert report["joint_eligible"] is False
    report = audit_holdout_receipts(d, rs, retained_snapshots=snap)
    assert report["holdout_counts"]["passed"] == 8
    assert report["joint_eligible"] is False


def test_holes_are_missing_and_later_receipts_keep_frozen_ordinal():
    d = declaration()
    snap = snapshots(d)
    rs = [receipt(d, i) for i in (0, 2, 3, 4, 5, 6, 7)]
    report = audit_holdout_receipts(d, rs, retained_snapshots=snap, primary_eligible=True)
    assert report["holdout_counts"] == {"passed": 7, "failed": 0, "unknown": 0, "missing": 1}
    assert report["first_problem"]["holdout_id"] == "h1"


@pytest.mark.parametrize("damage", ["private", "extra", "nonbytes", "oversized"])
def test_snapshot_input_is_bounded_and_closed(damage):
    d = declaration()
    snap = snapshots(d)
    if damage == "private":
        snap["h0"]["prompt"] = b"private"
    elif damage == "extra":
        snap["undeclared"] = snap["h0"]
    elif damage == "nonbytes":
        snap["h0"]["input"] = "not bytes"
    else:
        snap["h0"]["input"] = b"x" * (4 * 1024 * 1024 + 1)
    with pytest.raises(HoldoutAuditError):
        audit_holdout_receipts(d, [], retained_snapshots=snap)


def test_parser_rejects_oversized_invalid_unicode_and_nested_duplicates():
    with pytest.raises(HoldoutAuditError, match="too_large"):
        parse_holdout_declaration(" " * 65537)
    with pytest.raises(HoldoutAuditError, match="json_invalid"):
        parse_holdout_declaration("\ud800")
    d = declaration()
    text = json.dumps(d, sort_keys=True, separators=(",", ":"))
    text = text.replace('"ordinal":0', '"ordinal":0,"ordinal":0')
    with pytest.raises(HoldoutAuditError, match="duplicate_key"):
        parse_holdout_declaration(text)


@pytest.mark.parametrize("field,value", [
    ("cleanup", []), ("outcome", []), ("duration_ms", True),
    ("native_exit_code", False), ("process_exit_code", "0"),
    ("prompt", "private"),
])
def test_receipt_rejects_type_confusion_and_private_fields(field, value):
    d = declaration()
    r = receipt(d, 0)
    r[field] = value
    with pytest.raises(HoldoutAuditError):
        build_holdout_receipt(r)


def test_only_boolean_primary_projection_is_accepted():
    with pytest.raises(HoldoutAuditError, match="primary_eligibility_invalid"):
        audit_holdout_receipts(declaration(), [], primary_eligible="verified")


def test_receipt_text_requires_canonical_form_and_unique_keys():
    d = declaration()
    r = receipt(d, 0)
    with pytest.raises(HoldoutAuditError, match="noncanonical"):
        parse_holdout_receipt(json.dumps(r, indent=2), declaration=d)
    text = json.dumps(r, sort_keys=True, separators=(",", ":"))
    with pytest.raises(HoldoutAuditError, match="duplicate_key"):
        parse_holdout_receipt(text[:-1] + ',"outcome":"passed"}', declaration=d)


def test_public_holdout_api_exports_and_audit_remains_observation_only():
    names = {
        "HoldoutAuditError", "audit_holdout_receipts", "build_holdout_declaration",
        "build_holdout_receipt", "parse_holdout_declaration", "parse_holdout_receipt",
    }
    assert names <= set(lunar_evolution.__all__)
    assert names <= set(holdout_module.__all__)
    for name in names:
        assert getattr(lunar_evolution, name) is getattr(holdout_module, name)
    assert lunar_evolution.HOLDOUT_AUDIT_SCHEMA_VERSION == "1"
    assert lunar_evolution.HOLDOUT_MAX_DURATION_MS == 5000
    assert lunar_evolution.HOLDOUT_MAX_SNAPSHOT_BYTES == 4 * 1024 * 1024
    assert lunar_evolution.MAX_HOLDOUTS == 8
    d = declaration()
    snap = snapshots(d)
    receipts = [receipt(d, i) for i in range(8)]
    report = lunar_evolution.audit_holdout_receipts(
        d, receipts, retained_snapshots=snap, primary_eligible=True,
    )
    assert report == lunar_evolution.audit_holdout_receipts(
        d, receipts, retained_snapshots=snap, primary_eligible=True,
    )
    assert report["joint_eligible"] is True
    for flag in (
        "provider_called_during_audit", "executed_during_audit", "mutated_during_audit",
        "real_acceptance_claimed",
    ):
        assert report[flag] is False
    with pytest.raises(AcceptanceObservationError):
        lunar_evolution.parse_acceptance_manifest(report)
