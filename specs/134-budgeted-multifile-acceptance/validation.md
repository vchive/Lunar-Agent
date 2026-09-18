# Validation

Status: specification, implementation, offline verification and independent code review
are complete. Full regression passed. Preregistration, the sole real attempt and independent
postrun evidence audit are pending. No Feature 134 provider request has occurred.

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

## Pending verification

Clean pushed preregistration, the single real run and postrun audit
must complete before reporting this feature finished. A completed measurement is separate from
a successful product acceptance; an unsuccessful attempt remains the sole denominator.
