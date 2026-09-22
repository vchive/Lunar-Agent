from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution._audit_request import (
    AcceptanceAuditError,
    build_acceptance_audit_request,
    parse_acceptance_audit_request,
)
from lunar_evolution.acceptance_observer import (
    DEFAULT_ACCEPTANCE_BUDGETS,
    build_acceptance_manifest,
)
from lunar_evolution.holdout_audit import build_holdout_declaration


def _request_payload() -> dict[str, object]:
    manifest = build_acceptance_manifest({
        "schema_version": "1", "scope": "observation_manifest",
        "registration_id": "registration-new", "campaign_id": "campaign-new",
        "attempt_id": "attempt-001", "product_commit": "a" * 40,
        "campaign_root": "campaign-root-new", "task_sha256": "1" * 64,
        "input_sha256": "2" * 64, "evaluator_sha256": "3" * 64,
        "provider": "offline-provider", "model": "offline-model", "runtime": "python311",
        "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS),
    })
    identities = {
        "parent_run_id": "parent-run-new", "child_run_id": "child-run-new",
        "generation_task_id": "generation-task-new", "orchestration_task_id": "orchestration-task-new",
        "candidate_id": "candidate-new", "solve_execution_id": "solve-execution-new",
        "generation_budget_id": "generation-budget-new",
    }
    declaration = build_holdout_declaration({
        "schema_version": "1", "manifest_sha256": manifest["manifest_sha256"],
        "evaluator_sha256": manifest["evaluator_sha256"], "evaluator_version": "evaluator-v1",
        "candidate_id": identities["candidate_id"], "execution_sha256": "6" * 64,
        "holdouts": [
            {"holdout_id": f"holdout-{i}", "ordinal": i,
             "input_sha256": f"{i + 1:064x}", "expected_output_sha256": f"{i + 11:064x}",
             "max_duration_ms": 5000}
            for i in range(8)
        ],
    })
    return {
        "schema_version": "1", "scope": "acceptance_audit_request", "manifest": manifest,
        "identities": identities,
        "paths": {
            "parent_workspace": "parent/workspace", "child_workspace": "child/workspace",
            "plan": "plan.json", "admission": "admission.json", "execution": "execution.json",
            "evaluation": "evaluation.json",
        },
        "pins": {
            "contract_sha256": manifest["task_sha256"], "profile_sha256": "4" * 64,
            "bundle_sha256": "5" * 64, "plan_sha256": "7" * 64, "admission_sha256": "8" * 64,
            "completion_sha256": "6" * 64,
            "evaluation_sha256": "9" * 64, "selection_sha256": "a" * 64, "delivery_sha256": "b" * 64,
        },
        "holdout_declaration": declaration,
        "frozen_identities": {
            "registration_id": ["registration-old"], "campaign_id": ["campaign-old"],
            "campaign_root": ["campaign-root-old"], "parent_run_id": ["parent-run-old"],
            "child_run_id": ["child-run-old"],
        },
    }


def test_build_and_parse_round_trip() -> None:
    built = build_acceptance_audit_request(_request_payload())
    assert built["audit_request_sha256"]
    raw = json.dumps(built, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parse_acceptance_audit_request(raw) == built


def test_digest_and_exact_keys_are_required() -> None:
    built = build_acceptance_audit_request(_request_payload())
    forged = copy.deepcopy(built)
    forged["audit_request_sha256"] = "f" * 64
    with pytest.raises(AcceptanceAuditError, match="digest_mismatch"):
        parse_acceptance_audit_request(forged)
    forged = copy.deepcopy(built)
    forged["private"] = True
    with pytest.raises(AcceptanceAuditError, match="schema_invalid"):
        parse_acceptance_audit_request(forged)


def test_noncanonical_and_duplicate_json_are_rejected() -> None:
    built = build_acceptance_audit_request(_request_payload())
    raw = json.dumps(built, sort_keys=True, separators=(",", ":"))
    with pytest.raises(AcceptanceAuditError, match="noncanonical"):
        parse_acceptance_audit_request(json.dumps(built, indent=2))
    with pytest.raises(AcceptanceAuditError, match="duplicate"):
        parse_acceptance_audit_request(raw[:-1] + ',"scope":"acceptance_audit_request"}')


@pytest.mark.parametrize("path", [
    "/absolute", "a/../b", "a/./b", "a\\b", "a:", "a//b", "", ".", "..", "a/", "a\x00b",
    "a\nb", "a\x7fb", "a" * 513, "/".join(["a"] * 17), None, 1, True, [], {},
])
def test_paths_are_strictly_relative(path: str) -> None:
    payload = _request_payload()
    payload["paths"] = dict(payload["paths"])
    payload["paths"]["plan"] = path
    with pytest.raises(AcceptanceAuditError, match="path"):
        build_acceptance_audit_request(payload)


def test_manifest_and_holdout_cross_bindings_are_required() -> None:
    payload = _request_payload()
    payload["pins"] = dict(payload["pins"])
    payload["pins"]["contract_sha256"] = "f" * 64
    with pytest.raises(AcceptanceAuditError, match="contract_mismatch"):
        build_acceptance_audit_request(payload)
    payload = _request_payload()
    declaration = copy.deepcopy(payload["holdout_declaration"])
    declaration.pop("declaration_sha256")
    declaration["candidate_id"] = "other-candidate"
    payload["holdout_declaration"] = build_holdout_declaration(declaration)
    with pytest.raises(AcceptanceAuditError, match="holdout_binding"):
        build_acceptance_audit_request(payload)


def test_frozen_identity_reuse_is_rejected() -> None:
    payload = _request_payload()
    payload["frozen_identities"] = dict(payload["frozen_identities"])
    payload["frozen_identities"]["child_run_id"] = [payload["identities"]["parent_run_id"]]
    with pytest.raises(AcceptanceAuditError, match="frozen_identity_reused"):
        build_acceptance_audit_request(payload)


def test_request_size_and_frozen_list_bounds() -> None:
    payload = _request_payload()
    payload["frozen_identities"] = dict(payload["frozen_identities"])
    payload["frozen_identities"]["campaign_id"] = [f"campaign-old-{i}" for i in range(129)]
    with pytest.raises(AcceptanceAuditError, match="frozen_identities_invalid"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("section", [None, "identities", "paths", "pins", "frozen_identities"])
@pytest.mark.parametrize("change", ["extra", "missing"])
def test_every_request_section_requires_exact_keys(section, change) -> None:
    payload = _request_payload()
    target = payload if section is None else payload[section]
    if change == "extra":
        target["credential"] = "private-value"
    else:
        target.pop(next(iter(target)))
    with pytest.raises(AcceptanceAuditError) as caught:
        build_acceptance_audit_request(payload)
    assert "private-value" not in str(caught.value)


@pytest.mark.parametrize("field", [
    "parent_run_id", "child_run_id", "generation_task_id", "orchestration_task_id",
    "candidate_id", "solve_execution_id", "generation_budget_id",
])
@pytest.mark.parametrize("identity", [None, True, 1, [], "", "a" * 129, "a/b", "秘密"])
def test_identity_values_are_bounded(field, identity) -> None:
    payload = _request_payload()
    payload["identities"][field] = identity
    with pytest.raises(AcceptanceAuditError, match="audit_identity_invalid"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("field", [
    "contract_sha256", "profile_sha256", "bundle_sha256", "plan_sha256", "admission_sha256",
    "completion_sha256", "evaluation_sha256", "selection_sha256", "delivery_sha256",
])
@pytest.mark.parametrize("digest", [None, True, "A" * 64, "z" * 64, "a" * 63, "a" * 65])
def test_pins_require_lowercase_sha256(field, digest) -> None:
    payload = _request_payload()
    payload["pins"][field] = digest
    with pytest.raises(AcceptanceAuditError, match="audit_pin_invalid"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("field", [
    "manifest_sha256", "evaluator_sha256", "candidate_id", "execution_sha256",
])
def test_resealed_holdout_declaration_must_bind_current_request(field) -> None:
    payload = _request_payload()
    declaration = payload["holdout_declaration"]
    declaration.pop("declaration_sha256")
    declaration[field] = "other-candidate" if field == "candidate_id" else "f" * 64
    payload["holdout_declaration"] = build_holdout_declaration(declaration)
    with pytest.raises(AcceptanceAuditError, match="audit_holdout_binding_mismatch"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("field", ["registration_id", "campaign_id", "campaign_root"])
def test_frozen_manifest_identity_cannot_be_reused(field) -> None:
    payload = _request_payload()
    payload["frozen_identities"][field] = [payload["manifest"][field]]
    with pytest.raises(AcceptanceAuditError, match="audit_frozen_identity_reused"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("current", ["parent_run_id", "child_run_id"])
@pytest.mark.parametrize("historical", ["parent_run_id", "child_run_id"])
def test_frozen_run_identity_cannot_change_roles(current, historical) -> None:
    payload = _request_payload()
    payload["frozen_identities"][historical] = [payload["identities"][current]]
    with pytest.raises(AcceptanceAuditError, match="audit_frozen_identity_reused"):
        build_acceptance_audit_request(payload)


@pytest.mark.parametrize("entries,code", [
    (None, "audit_frozen_identities_invalid"),
    (("old",), "audit_frozen_identities_invalid"),
    (["old", "old"], "audit_frozen_identity_duplicate"),
    (["old/invalid"], "audit_frozen_identity_invalid"),
    ([False], "audit_frozen_identity_invalid"),
    (["a" * 129], "audit_frozen_identity_invalid"),
])
def test_frozen_list_validation(entries, code) -> None:
    payload = _request_payload()
    payload["frozen_identities"]["campaign_id"] = entries
    with pytest.raises(AcceptanceAuditError, match=code):
        build_acceptance_audit_request(payload)


def test_request_digest_binds_all_declarations() -> None:
    payload = _request_payload()
    built = build_acceptance_audit_request(payload)
    expected = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    assert built["audit_request_sha256"] == expected
    for section, field, replacement in (
        ("identities", "parent_run_id", "other-parent"),
        ("paths", "plan", "other/plan.json"),
        ("pins", "profile_sha256", "d" * 64),
        ("frozen_identities", "campaign_id", ["new-old-id"]),
    ):
        changed = copy.deepcopy(built)
        changed[section][field] = replacement
        with pytest.raises(AcceptanceAuditError, match="audit_request_digest_mismatch"):
            parse_acceptance_audit_request(changed)


def test_native_manifest_and_holdout_digests_are_required() -> None:
    for section, field, code in (
        ("manifest", "manifest_sha256", "audit_manifest_invalid"),
        ("holdout_declaration", "declaration_sha256", "audit_holdout_declaration_invalid"),
    ):
        payload = _request_payload()
        payload[section][field] = "f" * 64
        with pytest.raises(AcceptanceAuditError, match=code) as caught:
            build_acceptance_audit_request(payload)
        assert caught.value.__suppress_context__ is True
        assert caught.value.__cause__ is None


@pytest.mark.parametrize("value", [None, [], 1, True, b"{}"])
def test_non_objects_are_rejected(value) -> None:
    with pytest.raises(AcceptanceAuditError, match="audit_request_schema_invalid"):
        parse_acceptance_audit_request(value)
    with pytest.raises(AcceptanceAuditError, match="audit_request_schema_invalid"):
        build_acceptance_audit_request(value)


@pytest.mark.parametrize("value,code", [
    ("[]", "audit_request_schema_invalid"),
    ("null", "audit_request_schema_invalid"),
    ("{", "audit_request_json_invalid"),
    ("\ud800", "audit_request_json_invalid"),
    ("[" * 5000, "audit_request_json_invalid"),
    ("a" * (128 * 1024 + 1), "audit_request_too_large"),
    ("私" * (64 * 1024), "audit_request_too_large"),
    ('{"a":NaN}', "audit_request_json_invalid"),
])
def test_json_input_errors_are_bounded(value, code) -> None:
    with pytest.raises(AcceptanceAuditError, match=code):
        parse_acceptance_audit_request(value)


def test_nested_duplicate_keys_are_rejected() -> None:
    built = build_acceptance_audit_request(_request_payload())
    raw = json.dumps(built, sort_keys=True, separators=(",", ":"))
    raw = raw.replace('"plan":"plan.json"', '"plan":"plan.json","plan":"plan.json"')
    with pytest.raises(AcceptanceAuditError, match="audit_request_duplicate_key"):
        parse_acceptance_audit_request(raw)


def test_mapping_with_unserializable_values_never_exposes_private_exception() -> None:
    payload = _request_payload()
    payload["paths"]["plan"] = object()
    with pytest.raises(AcceptanceAuditError, match="audit_request_json_invalid") as caught:
        build_acceptance_audit_request(payload)
    assert caught.value.__suppress_context__ is True
    assert caught.value.__cause__ is None


def test_mapping_size_limit_and_cycles_are_rejected() -> None:
    payload = _request_payload()
    payload["paths"]["plan"] = "a" * (128 * 1024)
    with pytest.raises(AcceptanceAuditError, match="audit_request_too_large"):
        build_acceptance_audit_request(payload)
    payload["paths"]["plan"] = payload
    with pytest.raises(AcceptanceAuditError, match="audit_request_json_invalid"):
        build_acceptance_audit_request(payload)


def test_both_apis_return_independent_copies_without_mutating_inputs() -> None:
    payload = _request_payload()
    before = copy.deepcopy(payload)
    built = build_acceptance_audit_request(payload)
    parsed = parse_acceptance_audit_request(built)
    assert payload == before
    for value in (built, parsed):
        value["holdout_declaration"]["holdouts"][0]["holdout_id"] = "changed"
        value["manifest"]["budgets"]["solve_wall_seconds"] = 1
        value["frozen_identities"]["campaign_id"].append("changed")
        value["paths"]["plan"] = "changed.json"
    assert payload == before


def test_native_objects_are_required_for_nested_contracts() -> None:
    for section in ("manifest", "holdout_declaration"):
        payload = _request_payload()
        payload[section] = json.dumps(payload[section], sort_keys=True, separators=(",", ":"))
        with pytest.raises(AcceptanceAuditError):
            build_acceptance_audit_request(payload)


def test_safe_boundary_values_and_empty_denylist_are_explicitly_allowed() -> None:
    payload = _request_payload()
    payload["paths"]["plan"] = "a" * 512
    payload["paths"]["admission"] = "/".join(["a"] * 16)
    payload["identities"]["parent_run_id"] = "a" * 128
    payload["frozen_identities"] = {key: [] for key in payload["frozen_identities"]}
    assert parse_acceptance_audit_request(build_acceptance_audit_request(payload))["paths"] == payload["paths"]


@pytest.mark.parametrize("code", [None, 1, [], "private error /root", "a" * 65])
def test_error_constructor_only_preserves_bounded_public_codes(code) -> None:
    error = AcceptanceAuditError(code)
    assert error.code == "invalid"
    assert str(error) == "invalid"
