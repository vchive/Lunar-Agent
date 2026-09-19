# Feature Specification: Durable candidate-generation receipt

**Created**: 2026-09-19
**Status**: Specification-first; no provider request or generated-source execution

## Problem

The native automatic path emits an `agent_candidate_generation` diagnostic, but the controller
does not retain it with the parser-accepted source-bundle digest and candidate identity. A later
archive, execution, or evaluator record cannot prove that generation itself completed within the
registered tool budget. Feature 139 therefore has to report generation as unknown and cannot be
registered honestly.

## Scope

Add one durable, bounded receipt at the controller/Store boundary for every candidate-generation
attempt. The change must preserve current generation semantics, avoid retries, and remain useful to
read-only auditors after a process exit. This feature does not run a provider, execute generated
source, change selection policy, or reopen Feature 131/134.

## Contract

The persisted event is `agent_candidate_generation` and contains only safe metadata:

- schema version, registration/campaign/attempt identity, budget id, candidate id when parsing
  succeeds;
- `outcome` (`completed`, `failed`, or `unknown`) and a fixed reason code;
- `completion` boolean, `max_tool_steps`, `tool_steps_used`, `tool_steps_remaining`, and nullable
  `attempted_tool_calls`;
- `source_bundle_sha256` only after the native parser accepts a non-empty bundle.

The event is written exactly once for each admitted generation request, before any archive index
or downstream execution receipt. A failed or unknown event has no candidate or source digest. The
Store append is atomic and bound to the same run identity and budget id used by the request ledger.

## Acceptance

Read-only inspection must reject missing, duplicate, unbound, malformed, or budget-inconsistent
events. A completed receipt is valid only when parser acceptance, candidate identity, source digest,
and tool-budget arithmetic all verify. Downstream artifacts may corroborate the receipt but may not
create one. Existing event consumers and historical evidence remain byte-for-byte unchanged.
