# Tasks: WebAgent-Normal Workflow Checkpoints

- [x] T069-01 Review this SDD against Feature 068 authority, receipt, and privacy boundaries.
- [x] T069-02 Define and validate bounded master/checkpoint/state schemas and transition table.
- [x] T069-03 Implement the opt-in same-process staged controller around AgentLoopRuntime and SessionTranscript.
- [x] T069-04 Add offline tests for cooperative interruption, one-resume, budget carry-over, and redaction.
- [x] T069-05 Preserve EffectTrialRunner harness gating and add staged subject/CLI integration tests.
- [x] T069-06 Pre-register a two-arm, fixed-denominator measurement and independently audit its manifest.
- [ ] T069-07 Run the registered measurement, summarize per case, update HANDOFF, and publish audit evidence.

The 2026-09-10 integration replaces the earlier standalone fake-runner seam with actual AgentLoop
stages. The model-generated master plan is validated and passed to a fresh build transcript. A typed
cooperative boundary can resume once in the same process, with one ledger and absolute aggregate
deadline. Final runtime metadata includes all stages. Unknown/rejected provider consumption, hard
timeout, transcript failure, changed checkpoints or repeated startup fail closed. Process-death
recovery is explicitly deferred; accepted-only snapshots cannot safely restore unknown spending.

The opt-in API is `run_subject_adapter(workflow_config=StagedWorkflowConfig(...))`; the CLI exposes
`effect-subject --workflow-config PATH`. The unchanged normal receipt builder and EffectTrialRunner
public-projection/receipt gate remain authoritative. No default workflow or historic campaign changed.

Offline coverage includes real AgentLoop + deterministic models, frozen configuration identity,
master-plan propagation, transcript pairing and immutable snapshots, aggregate usage/cost/model
telemetry, deadline carry-over, output retention, symlink replacements, duplicate/resumed invocation,
and the trial gate with a fixture harness. No real provider, WebAgent, or private harness was called.
Real measurement results and a measured claim about solution quality remain pending.

Verification on 2026-09-10: 828 full-suite tests passed (30.94 seconds), including 101 staged-focused
cases; `ruff check src/famou tests` and `git diff --check` passed. The command uses
`pytest -o addopts='' -q` so the terminal summary retains the explicit pass count.

T069-06 completed on 2026-09-10: see `measurement/README.md`, frozen `manifest.json`,
`prelaunch-audit.json` and `dry-run.json`. Four fresh slots (two cases × M/S), two fixed waves,
one attempt each; GLM-5.2, 5400 seconds / 200 tools / 8,000,000 tokens. Product source remains
`80f5af1`. Registration SHA `07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e`.
The independent actual-evidence audit and 26-check isolated dry-run passed without model calls;
874 full-suite tests, Ruff, Specify prerequisites and diff checks passed. No historical campaign
or default workflow changed. Commit registration before launch; T069-07 remains open.

T069-07 started: registration commit `454b521` was pushed before first dispatch at
2026-09-10 10:19:43 +0800. Slots 1/2 have subject-started evidence; slots 3/4 are queued behind
the fixed wave barrier. `measurement/launch-observation.json` is an initial observation, not a
result. The detached campaign process owns both waves; never relaunch. Final outcome audit pending.
