# Tasks: WebAgent-Normal Workflow Checkpoints

- [x] T069-01 Review this SDD against Feature 068 authority, receipt, and privacy boundaries.
- [x] T069-02 Define and validate bounded master/checkpoint/state schemas and transition table.
- [ ] T069-03 Implement the staged controller around the existing AgentLoopRuntime and SessionTranscript.
- [ ] T069-04 Add fake-runtime offline tests for interruption, one-resume, budget carry-over, and redaction.
- [ ] T069-05 Preserve EffectTrialRunner harness gating and add staged-controller integration tests.
- [ ] T069-06 Pre-register a two-arm, fixed-denominator measurement and independently audit its manifest.
- [ ] T069-07 Run the registered measurement, summarize per case, update HANDOFF, and publish audit evidence.

The first implementation slice is complete in `src/famou/workflow_checkpoint.py` with
`tests/test_workflow_checkpoint.py`. It provides a score-free durable control-plane seam: strict
manifest/master/checkpoint/state bindings, confined regular-file digests, atomic state replacement,
no-overwrite checkpoints, monotonic aggregate usage and elapsed-time ceilings, redacted plans, and
one-resume enforcement. These tests cover the control-plane boundary only; fake-runtime
interruption and staged runner tests remain part of T069-03/T069-04/T069-05. The implementation
deliberately does not yet invoke AgentLoop stages or change
EffectTrialRunner receipt/harness authority; T069-03 and T069-05 remain open until that integration
is designed and tested.

Offline verification passed for the new tests, runtime/transcript regression tests, Ruff, and the
full existing test suite. No model, provider, WebAgent, or private harness was called.
