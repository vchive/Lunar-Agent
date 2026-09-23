# Feature 153: producer bundle publication transaction

**Status**: SDD specification; implementation not started

## Problem

Feature 152 produces an authority-bound admission plan, but the plan is still an in-memory
intent. It does not reserve an archive prefix, describe per-candidate execution outcomes, or
make a partially published producer batch recoverable. Passing the drafts directly to the legacy
seed publisher would incorrectly require `SeedManifest` evidence and could mix producer bundles
with an unrelated archive state.

## Outcome

Define a separate, durable batch journal for producer bundle publication. The journal binds one
Feature 152 plan digest to the contract, execution authority, archive prefix, candidate order,
per-candidate receipts, and a terminal publication state. A later implementation will use the
journal to publish a complete native multi-file batch atomically and to resume only when every
independent byte and authority pin matches.

## Contract

- A journal is created from one `ProducerBundleAdmissionPlan` and one canonical archive-prefix
  digest. The plan digest and prefix digest are immutable for the lifetime of the batch.
- Candidate order is the plan order. Candidate IDs are derived before execution and cannot be
  replaced, reordered, or reused by resume.
- Each candidate has separate preparation, execution, evaluation, and publication receipts. A
  missing, duplicated, stale, or cross-batch receipt blocks publication.
- Every item is adjudicated before publication. Known local invalid items are recorded as
  rejected, while the admitted subset is published all-or-nothing. An empty admitted subset
  fails closed without changing the archive or active state.
- For the admitted subset, the archive, candidate source trees, sidecars, state snapshot, and
  journal terminal marker must agree before success is exposed.
- A failed pre-publication attempt may be resumed only from the exact journal and exact plan.
  An unknown or partially published result is terminal and fails closed; it cannot be repaired by
  silently replaying the producer or evaluator.
- Journal parsing is canonical, bounded, no-follow, and provider-free. It never executes source,
  calls a producer, or treats producer scores as local authority.

## Non-goals

This feature does not change the legacy single-file `SeedManifest` protocol, the existing seed
publisher, automatic solve defaults, AgentLoop defaults, producer launchers, schedulers, remote
transport, or real external campaign acceptance. It does not claim framework parity or model
effectiveness.

## Acceptance

1. A valid plan creates one canonical journal whose digest is stable across parse/serialize
   round trips.
2. Contract, evaluator, runner, dependency, environment, plan, and archive-prefix drift are
   rejected before any candidate or archive write.
3. Preparation, execution, evaluation, and publication receipt ownership is unique and ordered;
   duplicate or foreign receipts fail closed.
4. A mixed batch records every adjudication and publishes only the admitted subset once, with one
   terminal journal marker and no partial archive/state success; an all-rejected batch publishes
   nothing.
5. Injected failures before publication leave no committed subset; failures after publication are
   reported as unknown and cannot be retried through the same journal.
6. Resume accepts only the exact journal, source bytes, authority pins, archive prefix, and
   receipt set; stale, reordered, truncated, symlinked, or tampered files are rejected.
7. Existing single-file seed, native multi-file, worker, and acceptance regressions remain
   unchanged, and provider-free tests do not start a producer or model provider.
