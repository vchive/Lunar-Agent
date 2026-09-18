# Feature Specification: Public status projection and preparation recovery contract

**Created**: 2026-09-18  
**Status**: Implemented offline
**Input**: Feature 131/134 postrun observations, Feature 116/132 recovery semantics, and the
existing CLI/measurement status projectors.

## Problem

Preparation failures currently have three related but intentionally different states: the
persisted parent run state, the preparation attempt state, and the effective status shown by the
CLI. The distinction is correct for explicit recovery, but it is easy to misread when a failed
preparation leaves the parent row `running` while public status is `failed`. Separately, the
private transport ledger records an observed HTTP status for a completed exchange, while older
public result summaries omit that safe field. The next implementation must make both projections
explicit without changing historical evidence or turning a recoverable parent into a terminal
failure.

## User scenarios

### US1 - Read a failed preparation safely (P1)

Status JSON and text expose persisted parent status, effective/public status, preparation status,
recoverability, and the reason for their relationship. A preparation timeout or local validation
failure is publicly `failed` while a recoverable parent may remain persisted `running` so an
explicit continuation can reuse its contract. No private provider response, prompt, generated
source, or arbitrary exception text is exposed.

### US2 - Resume only an eligible preparation (P1)

An explicit resume may start one new preparation attempt when a runtime/wall failure is marked
recoverable and parent/attempt identity, input, policy, and required evidence still match. Existing
explicit continuation of a valid interrupted start, validated local diagnostic, or corrected
artifact budget remains supported. Capability rejection may be checked again but cannot request a
model while still unsupported. A cancelled or terminal parent, corrupted detail, or input/policy
drift is rejected without a model request or a second attempt; a prepared parent reuses its frozen
result without another preparation attempt.

### US3 - Inspect observed HTTP status (P1)

Public measurement results include a bounded `status` for the uniquely bound transport exchange
that belongs to each request. A successful response may expose `200`; a 4xx/5xx response exposes
that observed status; a timeout before response headers remains `null`. Usage, ledger success,
response body, or a later retry never fabricates a status.

## Requirements

### Status and recovery

- **FR-001**: Public status has stable fields for `status` (effective), `run_status`
  (persisted parent), `preparation_status`, `preparation_recoverable`, and a bounded reason or
  reason code. Existing status consumers remain compatible.
- **FR-002**: Effective status precedence is deterministic: explicit parent cancellation wins;
  materialization/evolution failure preserves composite failure even if intake succeeded; other
  terminal persisted states override preparation; preparation `failed`/`unknown` projects effective
  `failed`. A prepared result or successful child alone cannot promote a running parent to success.
  JSON, text, and solve use the same projection. Reading status never mutates the Store.
- **FR-003**: Persisted `running` is a supported recovery state after an incomplete preparation;
  it must not be rewritten to `failed` merely because effective status is `failed`. Text and JSON
  explain that recovery requires an explicit continuation.
- **FR-004**: Resume admission verifies parent/attempt identity, input/profile/policy binding,
  preparation evidence, and the existing recoverable flag for runtime/wall retries. All schemas,
  including legacy schema 1, require valid status and fields; malformed or duplicate interrupted
  starts are rejected. Preserve existing explicit continuation for validated local/capability
  failures, a valid interrupted start, and a corrected artifact budget; `recoverable` remains the
  runtime-retry advisory and does not authorize those other paths. Corrupt or mismatched details
  degrade to non-resumable `unknown`/`failed` and cannot create a request.
- **FR-005**: Cancelled, terminal, or already-prepared parents do not create a new preparation
  attempt. A valid explicit recovery creates at most one new attempt under the existing budget and
  request ledger; no implicit retry is added.

### Public transport projection

- **FR-006**: For each public request row, transport status is sourced only from one validated
  `request_index` + `request_sha256` exchange with matching stage and outcome. It is an integer in
  `[100, 599]` or `null`.
- **FR-007**: The public transport array aligns with `usage.requests`; duplicate indexes, missing
  bindings, disagreement with typed request status, invalid ranges, and multiple exchanges are
  rejected or projected as unknown according to the existing schema policy.
- **FR-008**: A response status is never inferred from usage completion, a successful ledger row,
  response bytes, provider error text, or a retry. Credentials, URLs, headers, request/response
  bodies, prompts, and generated source remain private.
- **FR-009**: Historical schema/results and retained Feature 131/134 evidence remain readable and
  byte-for-byte unchanged. New summaries may add a versioned safe field without rewriting old
  reports.

### Boundaries

- **FR-010**: Implementation is offline-only and does not call a provider, execute generated
  source, resume Feature 131/134, or alter frozen WebAgent/history measurements.
- **FR-011**: No database migration, global retry policy, remote cancellation claim, or new real
  campaign budget is introduced.

## Acceptance criteria

1. Fixtures for preparation failure, timeout, unknown detail, cancellation, terminal state, and
   successful preparation assert stable JSON/text fields and no Store mutation during read.
2. An admitted explicit continuation creates at most one new attempt. Runtime/wall recovery needs
   its recoverable flag; the existing interrupted/local/capability/budget paths retain their
   respective validated evidence and resource checks. Corrupt, mismatched, or terminal cases
   create no request and preserve the original parent state.
3. Public transport summaries preserve `200`, 4xx/5xx, and no-header timeout/null cases and reject
   duplicate, unbound, mismatched, or private transport rows.
4. Existing schema1-4 diagnostics, CLI status consumers, preparation and recovery regressions pass.
5. Feature 131/134 registrations, manifests, reports, results, audits, evidence, and hashes are
   unchanged; no provider or generated-code execution occurs.

## Non-goals

This feature does not change parent persistence semantics, infer provider-side completion, expose
transport payloads, retry failed requests automatically, or claim improved model performance or
WebAgent parity.
