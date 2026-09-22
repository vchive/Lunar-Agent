# Feature Specification: artifact/lifecycle and holdout receipt auditor

**Created**: 2026-09-22
**Status**: Implemented as a read-only Python API; provider execution remains outside scope

## Problem

Feature 147 can prove that an acceptance observation has a canonical manifest and an ordered
prefix of stage receipts. That structural result cannot, by itself, prove that the bytes named by
those receipts were produced by the registered execution, independently evaluated, selected, and
delivered to the parent. It also cannot distinguish a complete set of holdout receipts from a set
that merely reports successful messages.

The next product boundary is a provider-free, read-only semantic auditor. It must connect the
existing native validators into one bounded report, preserve inode and identity checks, and make
missing or unverifiable evidence explicit. The auditor is a post-observation tool; it is not a
launcher, a repair tool, or a substitute for a real acceptance registration.

## Scope

Feature 148 defines two cooperating audit surfaces:

1. **Artifact/lifecycle audit.** Recheck preparation, execution, independent evaluation,
   validity-first selection, and parent delivery as one identity-bound chain. Reuse
   `validate_automatic_solve_bundle`, `inspect_candidate_execution_record`,
   `inspect_candidate_evaluation`, and `inspect_bundle_parent_delivery` rather than introducing
   a parallel acceptance schema. The audit consumes an existing retained Store/workspace view and
   never writes to it.
2. **Holdout receipt audit.** Validate a frozen holdout declaration and the retained receipt set
   for each holdout. Check identity, ordering, output/result digests, native exit and cleanup
   observations, and the declared evaluator version. The auditor reads receipts and snapshots;
   it never executes candidate code, an evaluator, or a holdout.

The audit may report `verified`, `failed`, or `unverifiable` for each semantic boundary and may
return eligibility projections for primary and joint closure. These projections are evidence for a
future postrun decision. They do not increment Feature 142/147 counters, do not authorize a
provider request, and do not claim a real-model result when no registered attempt exists.

The current native execution-record schema has no independent cleanup observation. Consequently,
even otherwise successful retained v1 execution evidence produces `execution_cleanup_unknown`;
the combined API currently returns both eligibility fields as `false`. Adding native cleanup
evidence is a separate prerequisite for real acceptance, not a reason to infer successful cleanup
from an exit code or a later receipt.

Feature 139 is a closed historical slot. Its evidence and frozen preparation/primary/joint
values remain immutable. This feature may compare a historical inventory by digest when a release
audit requires it, but it must not reopen, relaunch, import, or rewrite that slot or its helpers.
Feature 131 and Feature 134 evidence receives the same immutable treatment.

## Acceptance scenarios

- **P1 — audit retained native evidence.** Given a fresh offline fixture, a read-only audit
  verifies the native links that have sufficient evidence and preserves absent cleanup as unknown.
  Changing one source, input, execution,
  evaluation, selection, or delivery binding makes that boundary non-verified and cannot be
  repaired by a later successful-looking receipt.
- **P1 — audit parent lifecycle.** Given a child that completed before parent delivery, a parent
  marked succeeded before the verified delivery event is rejected. A recorded cancellation or
  solve timeout followed by late success is also rejected.
- **P2 — audit holdout receipts.** Given the eight declared holdouts, only eight bound passes with
  matching retained outputs, successful native/process exits, and verified cleanup make the
  holdout projection complete. Seven passes leave one missing and joint eligibility false.
- **P2 — preserve the audit boundary.** Repeating an audit changes no retained file, database,
  event, or acceptance counter. Executable files remain data throughout inspection.

## Contract

### Inputs

The auditor accepts a canonical observation manifest and a bounded audit request containing:

- the manifest digest and one fresh attempt identity;
- a read-only Store/workspace root for the same attempt;
- the registered contract, input, evaluator/profile and budget digests;
- the candidate plan/admission pins needed by the native execution-record inspector;
- the expected evaluation and delivery digests when they were recorded;
- a holdout declaration with exactly eight ordered, unique holdout IDs, expected-output digests,
  and a 5,000 ms ceiling per holdout.

The request is path-confined and size-bounded. It rejects private fields, provider payloads,
prompts, credentials, endpoint values, arbitrary exception text, and undeclared files. A copied
directory is not automatically equivalent to the original execution record: when a validator
requires the original device/inode identity, relocation produces `unverifiable`. This feature
introduces no substitute attestation, reconstructed completion record, or inode bypass. Native
portable delivery validation may still pass independently, but it cannot promote an unverifiable
execution or evaluation record.

The Feature 147 manifest does not yet bind holdout declarations or lifecycle-specific evidence.
A separate canonical audit-request digest must bind those additional declarations and the
manifest digest together. It remains an observation contract, not a preregistration seal; checking
internal consistency does not prove that declarations existed before a real launch. Fresh-identity
checking compares a caller-supplied digest-bound denylist and does not open archived campaign
helpers. Registration/preflight code must supply the complete historical identities before any
future real attempt.

### Artifact/lifecycle semantics

The audit must check these links in order; a later link cannot repair an earlier failure or
unknown result:

1. **Preparation:** reuse `validate_automatic_solve_bundle` and require the durable prepared event,
   profile/evaluator artifacts and declared inputs to exist and match. The validator can accept an
   intake that has not prepared yet, so its return without an exception is insufficient alone.
   The retained request, preparation-request and preparation-wall policies must exactly match the
   manifest's 600/900/1,860-second values; missing policy evidence is unverifiable and disagreement
   fails the boundary. The manifest binds request/token ceilings as declarations; enforcement and
   actual consumption accounting remain part of the separate launch/measurement implementation.
2. **Generation:** require Feature 147's native generation receipt validation, one parser-complete
   admitted candidate, and matching source bundle, run, task, candidate and budget identities.
   Self-reported source, a success message, or a later artifact cannot fill a missing generation
   receipt. The fixed tool-step ceiling remains 12.
3. **Execution:** `inspect_candidate_execution_record` returns a recorded, identity-bound result
   for the registered plan/admission/bundle/contract. `uncertain`, changed, relocated, or
   mismatched records are not successful execution. A `recorded` record may describe failure;
   require a succeeded native result, zero exit and verified cleanup observations before calling
   this boundary verified. Preserve absent cleanup as unknown.
4. **Evaluation:** `inspect_candidate_evaluation` confirms the retained snapshot, evaluator
   bytes, input/output bytes, output contract, and canonical evaluation report. A producer score
   or self-reported output has no authority. Require report validity `1`, matching candidate and
   execution pins, and the existing evaluator contract; successful parsing alone is insufficient.
5. **Selection:** exactly one validity-first selection receipt binds candidate, execution,
   evaluation, generation, and plan digests. Invalid, unexecuted, or unscored candidates cannot
   be selected.
6. **Parent delivery:** `inspect_bundle_parent_delivery` confirms reciprocal parent/child links,
   selected evidence, delivery package, output journal, and terminal event. Child completion alone
   cannot establish parent success.

The report preserves the first failed or unverifiable boundary and bounded reason codes. It never
repairs files, replays a request, resumes a run, settles a task, or changes a counter.

The lifecycle check additionally binds the parent run, evolution child, contract, one controller
orchestration task with `orchestration=true`, and the retained `solve_execution` identity. The task
must belong to the parent and remain outside ordinary model scheduling. The observation must
retain the registered 3,000-second active-execution policy, and parent/orchestration success must
follow durable verified delivery. Event sequence numbers and a consistent Store read snapshot
establish order; wall-clock timestamps do not reconstruct a monotonic remainder. Missing sequence
evidence is unverifiable. Budget failure or cancellation recorded first cannot be replaced by
later completion. The audit reports extra execution/attempt identities under the one-slot
protocol; it never starts a continuation to reconcile them.

### Holdout receipt semantics

Each holdout receipt is canonical JSON with a schema version, manifest/evaluator/candidate/
execution identities, unique holdout ID, ordinal, declared input and expected-output digests,
actual output digest, native and process exit observations, cleanup observation, bounded duration, outcome, and
receipt digest. The declaration fixes the ordered holdout IDs and expected digests before any
receipt is observed.

The auditor rejects duplicate, extra, out-of-order, unbound, noncanonical, or tampered receipts.
Missing receipts are reported as missing and leave the set unverifiable. `unknown`, missing native
or process exit, failed cleanup, duration over 5,000 ms, or a digest mismatch is not a pass. An
output match is recomputed from retained actual and expected bytes and the frozen declaration;
a receipt's `passed` claim alone is insufficient. A
joint-eligibility projection requires every declared holdout to be a verified pass and requires a
verified primary lifecycle chain. The auditor does not run the holdouts to fill a gap.

### Output

The bounded report contains the manifest/attempt identity, per-boundary status, first problem,
verified digests, holdout counts (`passed`, `failed`, `unknown`, `missing`), and two explicit
projections:

- `primary_eligible`: semantic evidence is sufficient for a future postrun decision;
- `joint_eligible`: primary evidence plus every declared holdout is verified.

It also contains `provider_called_during_audit=false`, `executed_during_audit=false`,
`mutated_during_audit=false`, and `real_acceptance_claimed=false`. No prompt, source body,
credential, endpoint, arbitrary exception, or unbounded log may appear in the public projection.

## Non-goals

- No provider, model gateway, external framework, WebAgent, campaign launcher, or generated-source
  execution.
- No new scoring authority; the existing evaluator report remains authoritative.
- No automatic solve integration, worker scheduling, detached execution, or retry policy.
- No migration of historical evidence and no reopening of the closed Feature 139 slot.
- No claim that a provider-free fixture is an end-to-end acceptance result.
