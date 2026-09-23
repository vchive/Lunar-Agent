# Feature 153: producer bundle publication transaction

**Status**: Provider-free journal and read-only preflight slice; staged publication pending

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

- A journal is created from one `ProducerBundleAdmissionPlan`, one run/task identity, and one
  canonical archive-prefix digest. The plan digest, run identity, and prefix digest are immutable
  for the lifetime of the batch.
- The archive prefix covers append-order archive records, the current `state.json`, strategy
  configuration, active island assignments, and any seed-commit marker. A digest that omits state
  or reorders records is not a valid prefix authority.
- Candidate order is the plan order. Candidate IDs are derived before execution and cannot be
  replaced, reordered, or reused by resume.
- Candidate IDs are safe, deterministic hashes of the batch ID, plan ordinal, bundle ID, and
  bundle digest. Preflight rejects collisions with existing archive records and never calls a
  sequential `next_id` allocator.
- Each candidate mapping records its strategy, parent ID, generation, iteration, island ID, and
  the population configuration digest. The mapping is fixed before the first execution and is
  sufficient for `PopulationStrategy` to reconstruct active state.
- Each candidate has separate preparation, execution, evaluation, and publication receipts. A
  missing, duplicated, stale, or cross-batch receipt blocks publication.
- The transaction binds one canonical budget profile digest covering preparation requests,
  execution/evaluation limits, and the total wall-clock allowance. Resume cannot widen or replace
  that profile.
- Every item is adjudicated before publication. Known local invalid items are recorded as
  rejected, while the admitted subset is published all-or-nothing. An empty admitted subset
  fails closed without changing the archive or active state.
- For the admitted subset, the archive, candidate source trees, sidecars, state snapshot, and
  journal terminal marker must agree before success is exposed.
- A failed pre-publication attempt may be resumed only from the exact journal and exact plan.
  An unknown or partially published result is terminal and fails closed; it cannot be repaired by
  silently replaying the producer or evaluator.
- A pending item with no side effect may continue. Existing execution/evaluation evidence is
  reused only after exact receipt and inode/byte verification; `running`, `unknown`, timeout, or
  cleanup-unknown evidence never triggers a producer/evaluator replay and returns
  `recovery_required`.
- A nonzero process exit, invalid evaluator result, or independently verified cleanup failure is a
  known rejected item. Timeout, observer/cleanup unknown, missing evidence, and any uncertain
  write or commit state are `unknown` and make the whole transaction terminal.
- Journal bytes live in the system-generated
  `workspace/evolution/producer-batches/<batch_id>/` directory; callers cannot choose a sibling,
  symlink, or path outside the run workspace. The journal, stage tree, and recovery marker have
  fixed names, regular-file/no-follow checks, and bounded sizes. Journal parsing is canonical,
  bounded, no-follow, and provider-free. It never executes source,
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
   reported as unknown and cannot be retried through the same journal. A terminal marker and
   after-archive/after-state digests are required before success is exposed.
6. Resume accepts only the exact journal, source bytes, authority pins, archive prefix, and
   receipt set; stale, reordered, truncated, symlinked, or tampered files are rejected.
7. Existing single-file seed, native multi-file, worker, and acceptance regressions remain
   unchanged, and provider-free tests do not start a producer or model provider.
8. The preflight revalidates the existing candidate source/record/receipt tree before any batch
   write; archive/state drift or source tampering has zero side effects.
