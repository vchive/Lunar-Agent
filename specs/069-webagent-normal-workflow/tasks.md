# Tasks: WebAgent-Normal Workflow Checkpoints

- [x] T069-01 Review this SDD against Feature 068 authority, receipt, and privacy boundaries.
- [x] T069-02 Define and validate bounded master/checkpoint/state schemas and transition table.
- [ ] T069-03 Implement the staged controller around the existing AgentLoopRuntime and SessionTranscript.
- [x] T069-04 Add fake-runtime offline tests for interruption, one-resume, budget carry-over, and redaction.
- [ ] T069-05 Preserve EffectTrialRunner harness gating and add staged-controller integration tests.
- [ ] T069-06 Pre-register a two-arm, fixed-denominator measurement and independently audit its manifest.
- [ ] T069-07 Run the registered measurement, summarize per case, update HANDOFF, and publish audit evidence.

The control-plane and standalone staged subject seam are implemented in
`src/famou/workflow_checkpoint.py` and `src/famou/staged_workflow.py`, with tests in
`tests/test_workflow_checkpoint.py` and `tests/test_staged_workflow.py`. They provide a score-free
durable control-plane seam: strict
manifest/master/checkpoint/state bindings, confined regular-file digests, atomic state replacement,
no-overwrite checkpoints, monotonic aggregate usage and elapsed-time ceilings, redacted plans, and
one-resume enforcement. Fake-runtime tests now cover interruption, ledger carry-over, candidate
preservation, and duplicate resume. The standalone runner invokes AgentLoop stages but deliberately
does not change EffectTrialRunner receipt/harness authority; subject-adapter wiring and exact
harness integration remain T069-03/T069-05.

The runtime seam preserves default invocation semantics: `AgentLoopRuntime.run` accepts an explicitly
shared `UsageLedger` and cumulative tool-step offset, while omitted arguments keep the existing
per-invocation budget reset. The runner never creates a receipt or authorizes harness execution.

Offline verification passed for the new tests, runtime/transcript regression tests, Ruff, and the
full existing test suite. No model, provider, WebAgent, or private harness was called.
