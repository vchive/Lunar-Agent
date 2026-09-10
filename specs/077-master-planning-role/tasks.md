# Tasks: Explicit Master Planning Role

- [x] T077-01 Specify prompt ambiguity, minimal role/context contract and unchanged boundaries.
- [x] T077-02 Add failing actual-message and native-handoff tests, including special context characters.
- [x] T077-03 Implement the private Master-only prompt builder without other behavior changes.
- [x] T077-04 Run isolated focused checks, Ruff, Specify and diff review; record the evidence.
- [ ] T077-05 Complete independent review and root-owned integration after Feature 076 evidence sealing.

No provider, private harness, WebAgent or historical candidate is executed. Passing deterministic
tests establishes the message/authority contract, not a cause for the observed timeout or a promise
of successful real planning.

Verification on 2026-09-10:

- Confirmed `famou.staged_workflow.__file__` resolves to this isolated worktree using explicit
  `PYTHONPATH` with the root development virtualenv.
- Before changing source, the new actual-message suite had **12 failures and 2 passes**: staged
  cases failed because the planning role was absent at the front; the non-staged normal/deep
  cases already passed. Existing rejection/accounting assertions in the reused fixtures passed
  before the new message-contract assertion failed.
- After the helper change, **14 tests passed**. The test author independently reran them with
  **14 passed in 0.39 seconds**, Ruff and diff checks passing. The special task contains Unicode,
  CRLF, a JSON fence and both context-label strings; it remains one complete unmodified context.
- Full external system-message hashes (default/custom, four model calls each, including the changing
  runtime budget messages) and complete tool-schema hashes match those captured from unchanged
  `1dacddb` fixture requests. Build/resume user messages match their original contract exactly;
  the accepted plan can defer unknown public columns while native receipt gates remain authoritative.
- The quickstart's seven-file targeted set passed **238 tests in 3.48 seconds**. Ruff, Specify and
  `git diff --check` passed. The only product change is the Master prompt helper and its call site.

Independent review approved the isolated implementation with no blocker, including Constitution
scope and unchanged native authority; the reviewer independently ran65 tests with isolated imports,
Ruff and diff checks. Root also reviewed the source/message diff and ran the full suite with
explicit isolated PYTHONPATH: **1359 passed in37.76 seconds** after the evidence preparation below.
T077-05 remains open only for root-owned integration after Feature076 evidence sealing. No real
model request, private evaluator, WebAgent or historical candidate was executed by this feature work.

Full-suite environment follow-up: the root agent's first isolated run reported 1358 passes and one
failure in `test_history_uses_sealed_074_chain_and_keeps_historical_samples_out` because a Git worktree
does not carry the ignored local historical evidence tree. The source was unchanged. Against sealed
Feature 074 manifest `b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229`, eight missing
historical report/manifest files were identified, their main-checkout bytes verified against its
historical SHA map, and copied with exclusive creation to the same isolated paths:

- `.lunar/high-score-case-selection-20260909/baseline-audit.json`
- `.lunar/real-eval-glm-5.1-20260909/manifest.json`
- `.lunar/real-eval-glm-5.1-budget-diagnostics-20260909/manifest.json`
- `.lunar/real-eval-glm-5.1-variant-v2-20260909/manifest.json`
- `.lunar/real-eval-glm-5.2-high-score-20260909/{audit,manifest,readiness,summary}.json`

All copied bytes matched their pins and source bytes. No Feature 076 data, candidate, solver,
credential, test, manifest or source change was introduced. The previously failing test then passed
in 0.06 seconds. This prepares only the local historical-test environment; a full rerun is root-owned.
