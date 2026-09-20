# Validation

## Authorized 50-minute preregistration revision (2026-09-20)

The user authorized the single real acceptance attempt and requested 50 minutes instead of
40 minutes before launch. The prior active manifest was copied byte-for-byte to
`measurement/registrations/unlaunched-40min.json` before its active-path removal. Archive size:
30,853 bytes. Archive SHA-256: `26fb2d8b447fd5f5b848016a55e041c5f273903f610d4b7c39c0bf10613f19f9`.
The bytes matched the committed active manifest at the time of archival. The old campaign root
`.lunar/real-automatic-multifile-closure-20260920` was absent, including no symlink. There was no
admission, worker, attempt, or provider request. The archived registration is **superseded before
admission** and contributes neither a failed run nor a retry/replacement to the one-attempt count.

The revised registration/campaign/root all use the `-50min` suffix and freeze a 3,000-second total
wall limit; all other fixed conditions and the product pin stay unchanged. The active manifest
will be recreated only after this revision is tested and committed/pushed. Worker and supervisor
propagation, prior-manifest archive discovery, inventory coverage, and the complete Feature 139
offline suite must pass before that fresh registration. The earlier full-regression numbers below
remain the prior implementation checkpoint and are not claimed as a rerun of this revision.

Revision validation results:

- Complete Feature 139 offline suite: **369 passed**, exit 0; the collection contains the previous
  363 tests plus 6 focused preregistration-revision tests. No whole-repository rerun is claimed.
- The focused revision tests lock the archived bytes/hash, prove only the three identities and
  total wall value changed in the fixed contract, and verify archived registration/campaign/root
  reuse is rejected. The archive is discovered by both measurement inventory and prior manifests.
- The actual worker receives a 3,000-second runtime guard and completes the native synthetic
  5-request/2-candidate/8-holdout path. A deterministic supervisor fixture accepts work after
  2,400 seconds and at 2,999 seconds, stops at 3,000 seconds, and performs bounded cleanup.
- Ruff, compileall, Specify prerequisites and `git diff --check` passed. The Specify script's
  temporary feature-pointer write was restored; no global pointer change is part of this revision.
- All 80 product files and 36 tracked historical files pinned by the archived manifest still
  match their exact byte sizes and SHA-256 values. Both old and new real campaign roots remain
  absent, and the active manifest path remains absent pending fresh registration.

No real provider request, production registration/admission, or worker/supervisor launch occurred
during revision validation. Tests use temporary fixtures and substituted local provider transport.

## Status

Offline harness, native mapping, registration, observer, worker, supervision, and retained-evidence
summary integration are implemented and independently reviewed as of 2026-09-20. B001–B011 and
the request/stage timing defects are closed in offline validation. T007 full current/frozen
historical regression passed with overall exit 0. At this offline implementation checkpoint no
registration, provider request, or real campaign launch has occurred. Native CLI fixtures execute fresh synthetic
candidates/evaluators with substituted HTTP responses; no historical generated source is executed.
Feature 131/134 and WebAgent are not reopened.

Feature 140 now persists canonical `agent_candidate_generation` receipts. Feature 141 adds the
explicit CLI candidate budget required by the proposed native run. The campaign mapping validates
the Store envelope, deterministic event ID, run/task/budget/candidate identity, registered step
ceiling, and parser-accepted bundle digest. Missing, failed, conflicting, or unbound evidence
remains unknown; downstream artifacts do not establish parser completion.

The 2026-09-19 [preregistration audit](preregistration-audit.md) found six blockers:
request-to-stage identity binding, ledger-policy binding to the manifest, total/preparation wall
and closure-reason evidence, immutable first closure, immutable registration, and the unknown
holdout joint-success gate. Corrections for B001–B006 and the worker/observer/supervision and
registration/file-inventory implementations have passed independent closure review. A concrete
manifest has not been created. The retained-artifact integration now exercises the actual native
CLI, Store, receipts, archive, delivery and summary; this remains offline evidence, not launch proof.

The 2026-09-20 entrypoint review identified three additional integration defects: the retained
summary did not consume the native generation receipt verifier; the worker redirected ordinary
CLI text into a binary stream; and summary stage validation omitted `holdout_gate`. T006a–T006c
are implemented and directly validated. Subsequent review also fixed the evaluator preparation
ceiling incorrectly capped at 600 seconds and re-entry after an early failed worker setup.
Effective request timeout overruns, preparation requests outside their trace window, local stages
after the worker endpoint, and a contract request incorrectly using the 900-second evaluator
allowance are rejected by the success gates. The completed full regression is recorded below.

## Previously completed validation (2026-09-19 baseline)

The native receipt and Feature 140 focused suite passed 134 tests; the independent Feature 139
audit suite passed 120 tests while reproducing the six gaps. The combined Feature 141/139 budget,
CLI, Agent, and receipt suite passed 409 tests. Static checks passed. These are offline checks of
that baseline, not proof that all preregistration criteria below have been met.

The combined full regression passed: current 8166 passed / 1 skipped / 24 deselected, immutable
Feature 123 stage 24 passed, overall exit 0. The product change was committed and pushed as
`87d86d9bc78171e7ce772dd9069e133249b81312`; `case.py` now uses that revision as its offline reference.
This replaces the earlier placeholder and does not create a sealed registration. These baseline
totals do not validate the later working-tree corrections or close T005a/T006a–T006c/T007.

## Offline exit criteria before registration

- Registration fixtures reject dirty or unpushed pins, changed product/provider/task/input/policy,
  reused roots, duplicate IDs, retries/replacements, request 21, and all budget drift.
- Stage fixtures cover preparation success/failure/unknown; candidate parser completion versus
  tool-budget exhaustion, timeout, empty/malformed response; execution success/failure; independent
  score validity; selection drift; interrupted/uncertain delivery; holdout mismatch; and cleanup
  uncertainty.
- A synthetic success contains at least one `completed` candidate and verifies the exact chain:
  preparation -> candidate generation -> execution -> independent scoring -> selection -> parent
  delivery. Its `primary_success` and `joint_success` are `1/1` only when all required gates pass.
- Synthetic failures retain denominator `1`, preserve unknown usage/status, and never promote a
  partial source tree, preparation result, self-reported score, or holdout-only result.
- Public summaries contain only allow-listed metadata and hashes. No prompt, response body,
  credential, URL, generated source, or arbitrary exception string crosses the projection.
- Feature 131/134 manifests, results, reports, audits, evidence, registrations, and retained
  files have identical byte sets and SHA-256 inventories before and after offline validation.
- Native receipt projections distinguish canonical, bound parser-complete Store receipts from
  transient/unbound diagnostics and never synthesize `completed` from downstream artifacts.
- Actual `runner.summarize()` / `analysis.summarize()` integration reads temporary retained native
  Store/workspace evidence and invokes the generation receipt verifier. Complete chains can pass;
  missing/failed/malformed/conflicting/tampered generation receipts cannot add a completed
  candidate or produce primary/joint success despite later execution, score, selection or delivery.
- The same summary integration checks the actual request/stage/budget/artifact links and preserves
  retained file bytes and SQLite/WAL. Provider, candidate and evaluator invocation sentinels remain
  unused throughout inspection; an isolated `ClosureCampaign` fixture is insufficient.
- Direct `worker.main()` fixtures use a synthetic native CLI that prints JSON as ordinary text.
  The exclusive UTF-8 capture is parseable, native exit and terminal records are retained, and an
  existing capture file is not overwritten. No binary-stdout `TypeError` can replace a valid run.
- Worker and retained-summary integration recognize `holdout_gate`. Missing primary completion,
  invalid output or source evidence leads to no holdout invocation, a bounded failed stage, and
  `0/1` primary/joint without a stage-validation crash or fabricated known values.

## Current offline validation record (2026-09-20)

- The Feature 139 suite contains 363 tests. The 362-test suite snapshot passed, followed by a
  passing targeted regression for the contract request timeout ceiling; all 363 were included in
  the final passing full current regression below.
- Direct native `worker.main()` with substituted HTTP responses completed 5 model requests,
  2 parser-complete candidates, isolated execution, independent scoring, selection, parent
  delivery and all 8 holdouts. The retained summary reports primary/joint `1/1`, quality 3 and
  gap 0 for this synthetic fixture only.
- Native failures cover contract, compiler/auditor, provider and candidate/source boundaries.
  Missing primary/output/source evidence prevents holdout invocation; `holdout_gate` is retained
  and summarized as `0/1`. Unknown usage/status stays explicit. Pending or absent request
  evidence, unbound identities, budget stops, timing drift and malformed retained markers cannot
  produce success. Existing captures and first worker terminal records are not overwritten.
- Read-only summary and receipt verification reject missing/failed/conflicting generation
  receipts and revalidate actual execution, scoring, selection and delivery materials. Provider,
  candidate, evaluator, mutating constructors and seed-recovery sentinels remain unused during
  analysis. Preserved SQLite/WAL and all retained file bytes remain unchanged; a second summary
  refuses to overwrite the first publication.
- Independent review closed B001–B011 and the timing counterexamples. See the
  [preregistration audit](preregistration-audit.md) for the original findings and focused review
  commands; overlapping test subsets must not be added as a unique total.
- Ruff across `src`, `tests` and this Feature 139 directory passed. Compileall, Specify
  prerequisites and `git diff --check` passed.
- Feature 131 retained inventory remains 21 files / 155485 bytes; Feature 134 remains 97 files /
  327394 bytes. File sets, sizes and SHA-256 values match their historical evidence. Their tracked
  historical file sets, respectively 15 and 21 files, are byte-identical to `57bd00d`.
- `tools/run_tests.py` completed with overall exit 0: current **8409 passed, 1 skipped,
  24 deselected in 668.93s**; fixed Feature 123 stage **24 passed in 22.92s**. JUnit records are
  `.lunar/test-results/feature139/current.xml` and
  `.lunar/test-results/feature139/frozen123.xml`.
- After the full run started, registration inventory coverage was narrowly extended to include
  the shared Feature 113 runtime guard and Feature 134 synthetic test fixture. This final inventory
  change passed 18 `registration_store` tests, static validation and final inventory checks. The
  already-running full suite did not reload that change; no second full-suite run is claimed.

T007 and offline implementation review are complete. At this checkpoint commit/push, a concrete
sealed manifest, unused-root and unique-slot launch preflight, and the one real provider attempt
remain separate work. Subsequent registration status is determined by `measurement/manifest.json`
and read-only launch checks. T008 verification evidence is retained locally under ignored paths;
these frozen offline documents need not be rewritten after registration.

## Planned commands

```sh
.venv/bin/pytest -q tests/test_measurement139_*.py tests/test_status_projection.py \
  tests/test_preparation* tests/test_bundle* tests/test_evolution* \
  tests/test_materialization* tests/test_producer_handoff.py
.venv/bin/ruff check src tests specs/139-real-multifile-closure
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
```

The exact campaign-local test paths may be adjusted during T002, but the commands must remain
provider-free before launch. The full current regression and its frozen historical stage are
required before T008.

## Launch and postrun evidence requirements

Before T009, retain the pushed manifest hash, product commit, clean-tree proof, identity checks,
unused-root proof, and test/inventory results. Verify `HEAD == origin/main` and that the manifest
contains the proposed fixed budgets.

After T009, retain one attempt only. The postrun result must report preparation, completed
candidates, execution, independent scoring, selection, delivery, holdouts, cleanup, request
counts, bounded transport statuses, and known/unknown usage. Each stage must be linked by its
registration/campaign/attempt IDs and digests. A missing or conflicting receipt is failure or
unknown, never inferred success.

The independent audit must read retained evidence without provider calls or generated-source
execution, verify the final package read-only, and confirm historical Feature 131/134 SHA
inventories. The final report must explicitly state whether primary and joint are `0/1` or `1/1`.

Passing offline checks demonstrates only that the measurement can observe the intended closure.
Even a successful run establishes one bounded current-version result; it is not WebAgent parity,
general model quality, or evidence for OpenEvolve/Shinka producer effectiveness.
