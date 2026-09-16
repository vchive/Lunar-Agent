# Feature 112 validation

Date: 2026-09-16. Tests use deterministic local runtimes and real local candidate/evaluator
processes. No real provider, WebAgent, external framework or new effectiveness campaign is run.

## Acceptance

- Snapshot evaluator compilation reuses the existing strict envelope, static source validation,
  separate auditor, invalid constraint probes and valid score ordering. Preflight exercises the
  actual 108 request/report interface and rejects malformed reports, changed snapshots and process
  limit violations. Default candidate invocation and legacy bundle identity remain compatible.
- Automatic preparation derives exact inputs, creates an ordinary profile and indexes all frozen
  materials. Reuse preserves bytes/events and compiler/auditor counts. Input, profile, evaluator,
  artifact and prepared-event drift fail. Current artifact budgets are enforced after callbacks.
- Conversational tests cover fresh solve, clarification/answer, inferred-mode solve and generic
  resume, explicit mode conflicts, drift before answer mutation, and frozen-but-not-yet-profiled
  interruption recovery. Ordinary parent delivery also verifies automatic preparation evidence.
- The standalone subprocess quickstart completes intake, compiler/auditor preflight, four scored
  candidates and parent delivery. Terminal resume retains counts `1 / 1 / 1 / 4 / 4` for contract
  compiler/evaluator compiler/auditor/Agent/candidate, with one delivery copy. Log:
  `/private/tmp/lunar112-quickstart.log`.

## Verification status

Focused new suites passed: **27** snapshot evaluator cases, **35** automatic preparation/recovery
cases and **32** conversational CLI cases (**94** new cases total). Existing evaluator and
conversational bundle regressions also passed. Independent review identified and verified fixes
for automatic preparation checks in ordinary delivery and budget changes during evaluator audit.

After product freeze, the complete suite passed: **5371 passed, 1 skipped in 357.87s**. JUnit
confirms 5372 tests, zero failures and zero errors, including all 94 new cases. The existing
case-alias test skips on this case-sensitive filesystem. Logs: `/private/tmp/lunar112-full.log`
and `/private/tmp/lunar112-full.xml`. No product or test changes followed this run.

The standalone quickstart passed again after product freeze. All-src/tests Ruff, compileall,
installed CLI help, Specify prerequisites, 100 local document links and `git diff --check` passed.
Frozen `specs/051*`, `074*`, `076*`, `078*` and `082*` have no changes relative to `027a235`.
This completed increment is committed and pushed to `origin/main` under the user's instruction.

## Limits

Probe success demonstrates the tested behavior, not complete business correctness or real-model
task quality. Existing input-format/probe capacity limits apply. Automatic profiles use local
Python and explicit settings; they do not install dependencies or authenticate host packages.
Per-invocation timeouts do not provide a global wall-clock budget across the entire preparation.
Frozen evidence and Store remain necessary for recovery. Active-process cancellation, detached
bundle solve, external multi-file seeds and real effectiveness measurement remain separate work.
