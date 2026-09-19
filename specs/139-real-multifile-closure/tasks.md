# Tasks

- [ ] T001 Freeze the six-stage closure contract, primary/joint gates, privacy boundary, one-slot
      denominator, and non-goals; review Feature 134's failure evidence without modifying it.
- [ ] T002 Trace the current native automatic preparation, candidate generation, execution,
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
- [ ] T006 Implement the campaign-local manifest, worker/observer, bounded ledger, read-only
      analysis, and postrun report/audit using the pinned native automatic path. Do not modify shared
      product code or make a provider request during implementation.
- [ ] T007 Run focused tests, current full regression, frozen historical stage, Ruff, compileall,
      Specify checks, diff checks, and independent historical inventories. Resolve all failures
      before registration; record exact test counts and manifest hash.
- [ ] T008 Freeze and push the new registration and product pins, verify clean `HEAD == origin/main`,
      unused campaign root, and one-slot admission. This task is a gate; it does not itself call a
      provider.
- [ ] T009 Launch the sole real attempt under the fixed budgets and supervise cleanup. Stop model
      admission at the first terminal/unknown budget or ledger condition; do not retry, resume,
      replace, repair, or append a request.
- [ ] T010 Summarize once and independently audit retained preparation, candidate, execution,
      scoring, selection, delivery, holdout, request, and cleanup evidence. Mark primary/joint only
      when at least one completed candidate satisfies every gate.
- [ ] T011 Update handoff/readiness/roadmap with the bounded outcome and limitations, mark this SDD
      complete, commit, and push. Preserve the one-attempt denominator and all historical files.
