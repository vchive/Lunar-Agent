# Research: Famou-Bench Adapter Boundaries

## Verified source facts

- Feature 048's subject and harness processes already receive separate explicit environment
  allowlists and attempt workspaces.
- Lunar's repository-owned `AgentLoopRuntime` provides read/write/list/command tools and can run a
  fresh Hermes-style session without importing Hermes.
- The inspected Famou Bench cases keep private scoring under `tests/`; the common chain calls
  `extractor_agent.py --evaluator ... --workspace ... --output ...`, then
  `evaluator.py --data-dir ... --submission-dir ...`.
- FM-Eval's current `container_runtime.harness.evaluate` uses that same two-step source contract,
  executes each stage once, and does not use `test.sh` as the generic entrypoint.
- FM-Eval explicitly treats SUT/harness separation as a credential/data-leakage boundary. Its
  evaluator receives no model credentials.
- The analytics results endpoint exposes per-run case, run index, readiness/projection state,
  extraction status, validity, overall score, quality, and telemetry. It does not by itself replace
  the immutable publication/CaseRevision/harness proof required by Feature 048.
- The current local lite benchmark checkout is `1.10.25`, not the historical `1.10.6` publication.

## Alternatives

| Alternative | Decision | Reason |
|---|---|---|
| Call `lunar-agent solve` as subject | Reject | Its durable DAG adds a different treatment and does not emit the strict subject receipt. |
| Use persistent memory during benchmark runs | Reject | Cross-run knowledge would invalidate independent shallow repetitions. |
| Run case `test.sh` | Reject | Scripts assume container absolute paths/install steps and are not the current generic FM-Eval contract. |
| Reimplement extractor logic | Reject | Changes what is measured and can silently repair subject output. |
| Import FM-Eval harness module | Reject | Couples Lunar to private service code/dependencies and its credential configuration. |
| Add authenticated service download | Defer | Local export conversion is sufficient and avoids credential/service coupling. |

## Result vocabulary

The adapter normalizes extractor `success` to Feature 048 `completed`; `partial`, `failed`, and
`error` remain invalid states and skip evaluation. Current FM-Eval projection `extracted` is also
normalized to `completed` during baseline conversion. Scores remain per-run raw evaluator values;
no best or aggregate is calculated by the converter.
