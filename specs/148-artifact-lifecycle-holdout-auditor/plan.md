# Implementation Plan: artifact/lifecycle and holdout receipt auditor

> **Boundary note (2026-09-22):** Feature 149 now supplies the independent cleanup-v1 receipt
> and native wiring referenced as a prerequisite below. This plan records the Feature 148
> checkpoint; fresh execution records use the Feature 149 contract and legacy records remain
> cleanup-unknown.

## Design

Implement the auditor as a read-only adapter over the existing acceptance observer and native
artifact validators. Keep semantic checks separate from Feature 147's manifest/receipt parser so a
structurally complete chain cannot be mistaken for a semantically verified one. The adapter must
be deterministic for a fixed read-only Store/workspace snapshot and must expose only bounded,
path-free reason codes and digests.

The audit request is a new envelope over Feature 147's unchanged observation manifest. Its digest
binds the manifest, native identities and pins, holdout declaration, expected stage artifacts, and
caller-supplied frozen identity denylist. Native schemas remain unchanged. No Store migration is
planned; the auditor must consume an established read-only view with writes, schema initialization,
and provider/runtime construction disabled. A Store copy belongs outside the retained tree, preserves
the original database/WAL bytes, and never substitutes new inode identity for native artifact
validation.

## Phases

1. **Contract and fixtures.** Define canonical audit-request, holdout-declaration, holdout-receipt,
   boundary-result, and final-report schemas. Add provider-free fixtures for preparation-only,
   execution-uncertain, evaluation tamper, selection mismatch, delivery mismatch, and complete
   holdout sets. Fixture identities are new and do not reuse historical campaign roots.
2. **Artifact/lifecycle adapter.** Add a read-only orchestration function that invokes the four
   existing validators in dependency order and reuses Feature 147's native generation parser.
   Require complete preparation receipts, successful execution telemetry, valid evaluation,
   selection identity, and successful delivery rather than treating a parser return as success.
   Cross-check the reciprocal child link, controller-owned orchestration task, 3,000-second solve
   policy, execution identity, and delivery-before-parent-success ordering. Pass exact native pins;
   preserve identity and inode failures and map exceptions to fixed audit reason codes. Use a
   read-only Store view and mark native artifact relocation as unverifiable without any bypass.
3. **Holdout auditor.** Parse the frozen declaration and canonical receipts, verify all bindings,
   order and bounded observations, and calculate pass/fail/unknown/missing counts without running
   any material. Require complete verified holdouts for `joint_eligible`.
4. **Combined report and release gate.** Combine the two projections, retain the first problem,
   expose explicit no-side-effect flags, and add an audit-only CLI/API entry point if the existing
   command surface can host it without changing launch behavior. Add negative tests for attempts to
   use the report as a launch manifest or to increment historical counters.
5. **Verification and documentation.** Run focused semantic-auditor tests, the existing Feature
   147 observer/inventory suites, shared lifecycle/evaluation regressions, Ruff, compileall, and
   diff checks. Record evidence as provider-free. A real acceptance attempt remains a separate
   preregistration under the Feature 142 plan.

## Invariants

- Every semantic result is bound to one manifest digest and one fresh attempt identity.
- The first failed or unknown stage is terminal for the audit projection; later artifacts cannot
  repair it.
- Native validators remain the authority for execution, evaluation and delivery semantics.
- Auditing never writes Store state, creates a child, changes a task, executes a subprocess, or
  calls a provider.
- `primary_eligible` and `joint_eligible` are projections only; official acceptance counters are
  unchanged by this feature.
- Feature 131, Feature 134 and Feature 139 retained bytes and result records remain untouched.

## Alternatives rejected

- **Recompute from a copied campaign directory:** rejected because execution records bind device/
  inode identity and copied bytes do not prove original launch provenance.
- **Trust stage receipts or producer scores:** rejected because receipts describe claims; native
  execution/evaluation/delivery validators must recheck the retained evidence.
- **Run holdouts during audit:** rejected because this feature is provider-free and read-only; a
  missing observation must remain unknown.
- **Make the auditor a launch preflight:** rejected to keep observation and authorization separate.

## Development quickstart

See [quickstart.md](quickstart.md) for the implemented provider-free focused tests, the Python audit
API, exact request fields, original-location requirements and report interpretation. The current
At the Feature 148 checkpoint, the native execution-record schema lacked independent cleanup
evidence, so a successful execution record left primary and joint eligibility false. Feature 149
supplies cleanup-v1 for fresh records; no launch command or provider call is part of this feature.

## Complexity tracking

The adapter introduces no new dependency, database schema, runtime adapter, scoring authority or
background process. Extra schemas describe only audit inputs/results and retained holdout receipts.
The native validators continue to own artifact validity; the new code owns cross-stage consistency
and explicit uncertainty. No constitution exception is planned.
