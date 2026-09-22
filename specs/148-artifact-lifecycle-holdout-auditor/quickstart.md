# Development quickstart

> **Boundary note (2026-09-22):** Feature 149 adds optional cleanup-v1 evidence to fresh native
> execution records. The legacy three-file examples in this guide remain cleanup-unknown; use
> the Feature 149 quickstart for the fresh receipt contract.

Feature 148 provides the Python API `audit_acceptance_artifacts` for inspecting retained evidence.
It does not provide a launch or continuation command. Run the following checks from the repository
root using the existing development environment:

```sh
./.venv/bin/python -m pytest --disable-warnings -ra \
  tests/test_audit_request.py \
  tests/test_audit_snapshot.py \
  tests/test_audit_lifecycle.py \
  tests/test_audit_slots.py \
  tests/test_holdout_audit.py \
  tests/test_acceptance_audit.py \
  tests/test_acceptance_audit_snapshot.py \
  tests/test_acceptance_audit_native.py \
  tests/test_native_delivery_readonly.py
```

The native audit fixtures write static canonical records and retain their original file identities;
they do not execute candidate source or an evaluator. The archive regression uses local callbacks
to create its fixture. These checks do not establish a real-model acceptance result.

Feature 147's shared observation checks are available separately:

```sh
./.venv/bin/python -m pytest --disable-warnings -ra \
  tests/test_acceptance_observer.py \
  tests/test_candidate_generation_receipt.py \
  tests/test_campaign_inventory.py
```

## Audit API

The caller supplies existing retained data. This function demonstrates the complete call shape
without assuming a campaign directory, manufacturing receipts, or executing missing evidence:

```python
import json

from lunar_evolution import (
    audit_acceptance_artifacts,
    build_acceptance_audit_request,
    parse_acceptance_audit_request,
)


def audit_retained_attempt(
    payload, *, database, audit_root, stage_receipts,
    holdout_receipts=(), retained_snapshots=None,
):
    # payload contains the fields below, without audit_request_sha256.
    request = build_acceptance_audit_request(payload)
    canonical_request = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    checked_request = parse_acceptance_audit_request(canonical_request)
    return audit_acceptance_artifacts(
        checked_request,
        database=database,
        audit_root=audit_root,
        stage_receipts=stage_receipts,
        holdout_receipts=holdout_receipts,
        retained_snapshots=retained_snapshots,
    )
```

`build_acceptance_audit_request` returns a detached mapping with `audit_request_sha256`.
`parse_acceptance_audit_request` accepts that mapping or its exact canonical JSON string. Parsing
checks internal bindings; it does not prove that a declaration existed before a launch.
`audit_acceptance_artifacts` accepts the same request forms. There is no caller-supplied
`primary_eligible` argument on the combined API.

## Request fields

The request has exact schemas; additional fields are rejected. The complete request is bounded at
128 KiB. SHA-256 values use 64 lowercase hexadecimal characters.

| Field | Required content |
| --- | --- |
| `schema_version` | `"1"` |
| `scope` | `"acceptance_audit_request"` |
| `manifest` | A parsed Feature 147 observation manifest, including its `manifest_sha256`. |
| `identities` | `parent_run_id`, `child_run_id`, `generation_task_id`, `orchestration_task_id`, `candidate_id`, `solve_execution_id`, `generation_budget_id`. |
| `paths` | `parent_workspace`, `child_workspace`, `plan`, `admission`, `execution`, `evaluation`. Workspace paths are relative to `audit_root`; the four artifact paths are relative to the child workspace. `execution` and `evaluation` name retained directories. |
| `pins` | `contract_sha256`, `profile_sha256`, `bundle_sha256`, `plan_sha256`, `admission_sha256`, `completion_sha256`, `evaluation_sha256`, `selection_sha256`, `delivery_sha256`. |
| `holdout_declaration` | A parsed, digest-bound declaration of exactly eight ordered holdouts. |
| `frozen_identities` | Lists named `registration_id`, `campaign_id`, `campaign_root`, `parent_run_id`, `child_run_id`; at most 128 unique entries per list. The caller supplies the complete historical identities. |

The contract pin must equal the manifest's `task_sha256`. `completion_sha256` binds the native
execution completion record; `evaluation_sha256` binds the native evaluation manifest;
`selection_sha256` binds the selected ordinary candidate receipt. The manifest's `input_sha256`
is the digest of the canonical declared input descriptor list, and `evaluator_sha256` is the
retained evaluator harness byte digest.

Preparation checks the retained `evolution_requested` policy against the manifest: `timeout`
600 seconds, `evaluator_preparation_timeout` 900 seconds and
`evaluator_preparation_wall_timeout` 1,860 seconds. Missing values remain unverifiable and
different values fail. The lifecycle separately requires an explicit 3,000-second solve policy,
and generation requires a native receipt with the 12-step ceiling. Request/token ceilings remain
bound declarations; launch enforcement and observed consumption accounting belong to the future
measurement implementation.

Relative paths cannot contain empty, `.` or `..` components, backslashes, colons or control
characters. They are bounded at 512 characters and 16 components. The root's final directory name
must match the manifest's `campaign_root`. The Store's parent and child workspaces must match the
declared paths, and the child workspace must be the parent's `evolution-run` directory.
The one-slot check additionally requires the native artifact layout: one
`evolution/bundle-attempts/.bundle-run-<24 lowercase hex>` directory containing `plan.json`,
`admission.json`, `attempt` and one `evaluations/.candidate-evaluation-<24 lowercase hex>` directory.
Extra run or evaluation entries, including empty or failed attempts, do not satisfy the one-slot
protocol.

`stage_receipts` is the retained Feature 147 receipt sequence for preparation, generation,
execution, scoring, selection and delivery. Present artifact digests must match the corresponding
audit pins. Native generation, execution, evaluation and delivery evidence is inspected separately;
a receipt's success claim does not complete those checks.

## Holdout data

Use `build_holdout_declaration`, `parse_holdout_declaration`, `build_holdout_receipt` and
`parse_holdout_receipt` from `lunar_evolution` for their existing in-memory schemas. A declaration
binds `manifest_sha256`, `evaluator_sha256`, `evaluator_version`, `candidate_id` and
`execution_sha256` to its ordered holdout list; the latter execution digest must match the audit
request's `completion_sha256`. Each holdout declares `holdout_id`, zero-based `ordinal`,
`input_sha256`, `expected_output_sha256` and `max_duration_ms` of at most 5,000.

Receipts bind that declaration and the same identities, input and expected-output digests, plus
`actual_output_sha256`, `native_exit_code`, `process_exit_code`, `cleanup`, `duration_ms`, `outcome`
and their canonical `receipt_sha256`. Both exits must be zero, cleanup must be `"verified"`, and
outcome must be `"passed"` before a matching retained result can pass. Canonical receipt JSON
strings or parsed mappings are accepted; duplicate, extra, reordered or unbound receipts are
rejected.

`retained_snapshots` is a mapping from declared holdout IDs to exactly three byte strings:

```python
{
    holdout_id: {
        "input": retained_input_bytes,
        "expected_output": retained_expected_bytes,
        "actual_output": retained_actual_bytes,
    }
}
```

Each byte string is bounded at 4 MiB. The auditor recomputes their digests and compares actual and
expected output commitments. Missing receipts count as `missing`; missing retained snapshots or
unknown exit/cleanup/outcome observations cannot count as passes. Supplying no receipts or
snapshots is allowed and reports incomplete evidence; the auditor does not produce them.

## Retained location and report interpretation

Keep the original workspace and evidence directories quiescent while auditing. Only SQLite and
its WAL are copied to a private temporary snapshot. Source database bytes are checked for changes,
and the original workspaces are inspected in place. Moving or copying an execution/evaluation
directory changes its device/inode bindings and produces `unverifiable`; byte equality alone is
insufficient. Seed recovery markers are left intact and rejected by read-only native archive
inspection. The audit never repairs or rewrites those records.

The report lists `receipt_chain`, `snapshot`, `preparation`, `generation`, `slot_identity`,
`execution`, `scoring`, `selection`, `delivery` and `lifecycle` boundaries. Each includes a status
(`verified`, `failed` or `unverifiable`), a bounded reason and any verified digests. `first_problem`
preserves the first non-verified boundary; later successful evidence cannot repair it.
`holdout_counts` contains `passed`, `failed`, `unknown` and `missing` counts.

`primary_eligible` requires every primary boundary to be verified. `joint_eligible` also requires
all eight holdouts to pass. At the Feature 148 checkpoint, the native execution-record schema had
no independent cleanup observation. A recorded, succeeded execution with exit zero therefore
yielded `execution_cleanup_unknown`, kept `primary_eligible=false`, and consequently kept
`joint_eligible=false`. Feature 149 adds cleanup-v1 for fresh records; a separately verified
scoring snapshot still does not fill a missing cleanup gap.

The report always sets `provider_called_during_audit`, `executed_during_audit`,
`mutated_during_audit` and `real_acceptance_claimed` to `false`. Its compatibility fields
`preparation_success`, `primary_success` and `joint_success` remain `"0/1"`; these are report
values, not writes to acceptance counters or replacements for frozen historical results.
Malformed request/receipt envelopes raise bounded `AcceptanceAuditError` or `HoldoutAuditError`
codes. The report is an observation artifact and cannot be passed as an observation manifest or
used to authorize another attempt.
