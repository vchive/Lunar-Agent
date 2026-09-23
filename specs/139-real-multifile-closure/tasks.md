# Tasks

Current preregistration gaps are tracked in [preregistration-audit.md](preregistration-audit.md).
The offline fixture suites, B001–B011 corrections, registration, observer, worker, supervision,
and retained-evidence analysis have completed independent offline acceptance on 2026-09-20.
T006a–T006c include actual worker/summary entrypoints and native Store/workspace evidence.
T007 final split regression passed. The original task list was intentionally frozen before
registration; its unchecked T008r3/T008–T011 boxes are retained as that pre-run checkpoint and
must not be interpreted as permission to rerun the old slot. The authoritative follow-up record
is [HANDOFF.md](../../HANDOFF.md): the new `-50min` registration was pushed, the sole real
`attempt-001` was launched and summarized once, and the postrun result is preparation `1/1`,
primary/joint `0/1` with no completed candidate. The old measurement implementation and its
private artifacts were later moved into `docs/history-archive.json` during the identity migration;
no current command may recreate or append to that historical slot.

## Pre-admission 50-minute revision (2026-09-20)

The user authorized the real attempt with a 50-minute total limit. The original 40-minute
registration had no root, admission, attempt, or provider request and is superseded before
admission; it is not a failed attempt or retry. Earlier text above records the offline checkpoint.

- [x] T008r1 Archive the original manifest without changing its bytes; record unused-root proof
      and the user's 3,000-second authorization in the SDD. Keep historical Feature 131/134 intact.
- [x] T008r2 Use new `-50min` registration/campaign/root identities and a 3,000-second whole-attempt
      wall limit; include the archive in inventory/prior-identity checks; prove unchanged other
      budgets/input/product pin and worker/supervisor timeout propagation in focused tests.
- [ ] T008r3 Commit/push the revision, create/push the new active manifest, and repeat read-only
      launch preflight. Admit only its sole `attempt-001`; do not run the archived registration.

- [x] T005a Independently re-audit the implemented B001–B006 corrections: request-stage bindings,
      sealed registration/ledger policy, immutable closure reasons and timing, and holdout outcome
      gates. Confirm every documented negative regression before T008.

- [x] T001 Freeze the six-stage closure contract, primary/joint gates, privacy boundary, one-slot
      denominator, and non-goals; review Feature 134's failure evidence without modifying it.
- [x] T002 Trace the current native automatic preparation, candidate generation, execution,
      independent evaluator, selection, and parent-delivery receipts; identify every shared identity
      and budget field needed by the campaign-local harness.
- [x] T003 [P] Build offline registration and launch-preflight fixtures for clean pushed pins,
      unique roots/IDs, provider identity, request/wall/token limits, and rejection of drift,
      duplicate attempts, retries, and post-slot requests.
- [x] T004 [P] Build offline stage-chain fixtures for preparation, parser-gated completed candidate,
      execution, independent score, selection, delivery, holdouts, cleanup, and all first-failure or
      unknown branches. Assert no later stage fabricates a missing earlier receipt.
- [x] T005 [P] Build public-result and audit fixtures for candidate/execution/evaluation identity,
      digest binding, source/input/output integrity, redaction, safe transport status, and historical
      Feature 131/134 byte/SHA preservation.
- [x] T006 Implement the campaign-local manifest tooling, worker/observer, bounded ledger, read-only
      analysis, and postrun report/audit using the pinned native automatic path. Do not modify shared
      product code or make a provider request during implementation. Integration acceptance below
      is complete; concrete manifest creation and real postrun artifacts remain T008/T010.
- [x] T006a Wire retained native generation receipts into the actual runner/analysis summarization
      path and verify all six native stages, requests, identities, budgets, and artifact bindings.
      Add temporary Store/workspace integration cases for complete success and missing, failed,
      malformed, conflicting, or tampered receipts; later delivery must not imply parser completion.
      Prove summary reads preserve retained bytes and call no provider/candidate/evaluator.
- [x] T006b Correct worker CLI output capture and directly test `worker.main()` with a synthetic
      text-printing native CLI. Verify exclusive UTF-8 JSON capture, no binary-stdout TypeError,
      no overwrite, native exit recording, and bounded worker terminal records.
- [x] T006c Admit `holdout_gate` as a bounded worker/summary failure stage. Direct worker and real
      summary integration fixtures must prove missing primary completion, invalid output, or
      invalid source evidence performs zero holdouts, summarizes without a stage error, and keeps
      primary/joint at `0/1` with unknown values preserved.
- [x] T007 Run focused tests, current full regression, frozen historical stage, Ruff, compileall,
      Specify checks, diff checks, and independent historical inventories. Resolve all failures
      before registration; record exact test counts and the final inventory verification.
- [ ] T008 Freeze and push the new registration and product pins, verify clean `HEAD == origin/main`,
      unused campaign root, and one-slot admission; record the concrete manifest hash and read-only
      launch checks in ignored local evidence. This task is a gate; it does not itself call a provider.
- [ ] T009 Launch the sole real attempt under the fixed budgets and supervise cleanup. Stop model
      admission at the first terminal/unknown budget or ledger condition; do not retry, resume,
      replace, repair, or append a request.
- [ ] T010 Summarize once and independently audit retained preparation, candidate, execution,
      scoring, selection, delivery, holdout, request, and cleanup evidence. Mark primary/joint only
      when at least one completed candidate satisfies every gate.
- [ ] T011 Update handoff/readiness/roadmap with the bounded outcome and limitations, mark this SDD
      complete, commit, and push. Preserve the one-attempt denominator and all historical files.
