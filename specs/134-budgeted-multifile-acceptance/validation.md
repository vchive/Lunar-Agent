# Validation

Status: specification, implementation, offline verification, independent code review, pushed
preregistration, the sole real attempt, postrun evidence audit and final report review are complete.
Full regression passed. Preparation passed, but product acceptance failed.

## Scope and test-first implementation

Product code remains fixed to Feature 133 commit `15710bd420d70aa07a06ee9dd4329dfbf1912b2b`.
Only new campaign measurement code/tests and SDD documents are implemented. Registration freezes
600-second candidate/ordinary requests, 900-second preparation requests, 1860-second preparation
wall time and the unchanged 2400-second/20-request/160000-observed-token campaign limits.

Tests first exposed lost typed request failures and registration drift, then passed after the
campaign-local fixes. The observer restores only the exact native failure after durable frozen
guard accounting; journal and admission failures retain precedence. Full-worker fixtures verify
request limits 600/900/900/600/600/600, explicit persisted policy, a candidate600 frozen profile
without preparation keys, success with eight holdouts, typed compiler/auditor failures and
deterministic preparation expiry with no child/profile.

Independent review identified and resolved complete product-file-set pinning, pre-slot provider
validation, native redirected HTTP exchange compatibility, wall expiry accompanied by an untyped
request failure, and the native integer-zero exit requirement for official quality/joint success.
Read-only verification and summary do not require current provider credentials. Native persisted
parent status remains independent of effective failure status.

## Completed offline checks

- All six Feature 134 suites: **262 passed in 28.52 seconds**.
- Focused subsets include 53 registration, 113 analysis and 44 observation/runner tests; these
  overlap with the total and are not additive.
- Feature 112 quickstart selects 7 from 1/2/6/7, produces one delivery and retains call counts
  1/1/1/4/4 after terminal resume.
- Ruff, compileall, Specify prerequisites, four local Markdown links and diff checks passed.
- Read-only provider identity matches Feature 131 exactly; no model request was made.

## Historical preservation

Independent read-only size/SHA inventories match all **131 files / 377335 bytes**: Feature 131
21/155485, 129 16/122657, 128 63/74305, 125 16/13017 and 123 15/11871. The existing tracked specs,
product source and pyproject file set and bytes also match HEAD: 1552 files / 8021040 bytes.
No historical generated source was executed and no retained SQLite database was opened.

## Full regression

The two-stage command in quickstart exited **0**. Current worktree: **7924 passed, 1 skipped,
24 deselected in 587.12 seconds**; JUnit records 7925 tests with zero failures/errors. Fixed
Feature 123 checkout: **24 passed in 14.64 seconds**, preserving 77 product / 14 measurement /
69 historical pins. No implementation changes were made after this regression started.

## Registered real attempt

Registration `358f7383e61aec9e702310774b0d5d906978c2f8` was pushed before launch with a clean
worktree and unused root. Manifest SHA-256 is
`20eb007b2d37b3b4a47d86795b8909213a64dffe36ad57055829c9deb9166ebf`; its pins contain 79
product, 20 measurement and 178 historical files. The sole run consumed `attempt-001` and
finished in 896.395714 seconds. No retry, resume, replacement or response repair occurred.

Preparation succeeded **1/1**, all holdouts matched **8/8**, but primary and joint success remain
**0/1**. Native and worker process exit codes are 1; cleanup is verified. Official quality and
gap remain null. All 11 requests completed with observed HTTP200 and complete recorded usage:
34088 input + 64626 output = **98714 tokens**; monetary cost is unknown. Neither preparation
request exceeded 600 seconds, so this result does not establish a benefit from the larger limit.

Summarization created `postrun/results.json` and `postrun/evidence.json` once without executing
models or generated code. Inventory contains 97 retained files / 327394 bytes. The frozen SDD
specification intentionally preserves its preregistration status; this validation and postrun
report record the later outcome.

Retained events identify three generation invocations stopped at `max_steps=4`, which counts
individual tools. Their consumed/requested-next-batch counts were 4+2, 4+2 and 3+2; all 11
previously executed tools succeeded. No complete candidate was returned or evaluated, and the
evolution child failed with `offspring_batch_failed`. The parent intake's persisted success and
the CLI's effective failure are separate, expected projections. No partial source was rerun or
promoted to repair the failed result.

## Independent postrun audit

Audit status is **passed with no blocking findings**: [audit.json](../../docs/history-archive.md). It verified
push-before-start chronology, all 79/20/178 registered pins, the 97-file / 327394-byte result
inventory, 11 single-exchange HTTP200 requests and complete 98714-token usage, preparation 1/1,
holdouts 8/8, primary/joint 0/1, native/process exit 1, cleanup and no matching retained process.
Historical evidence remains 131 files / 377335 bytes with unchanged sets, sizes and hashes. The
audit made no provider requests, did not rerun summarization or generated code, and read SQLite
only through a disposable private copy.

The bounded candidate diagnosis is [diagnosis.json](../../docs/history-archive.md). It binds manifest,
result and evidence hashes and records three in-run generation invocations stopped by `max_steps=4`
before candidate parsing: 4+2, 4+2 and 3+2 consumed/requested tool calls. All previously executed
tools succeeded; evaluated and valid candidates, execution evidence and delivery events remained
zero. It also confirms no native model profile was passed, so no remaining-tool advisory was
appended; the separate campaign guard remained active. This is a visibility gap and immediate stop
boundary, not proof that a larger limit or changed prompt would succeed.

A completed measurement is separate from successful product acceptance; an unsuccessful attempt
remains the sole denominator.
