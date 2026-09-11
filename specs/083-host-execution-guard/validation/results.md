# Feature 083 validation

Completed on 2026-09-11 on the local macOS host. The feature adds an opt-in process-owned
idle-system-sleep assertion and an independent clock/lifecycle journal around normal/deep CLI
trial calls or a Python supervisor operation. Default execution, model selection, native receipts,
scores, usage ledgers, HTTP transport and timeout budgets are unchanged.

## Verification

| Check | Result |
| --- | --- |
| Failure-first native boundary | 50 failures before implementation; final 55 pass |
| Failure-first journal/scope | 45 failures before implementation; final 71 pass |
| Failure-first CLI | 22 failures / 3 existing-path passes before implementation; final 37 pass |
| Related host/trial/deep/preflight suites | 222 pass, 5.21 seconds |
| Independent new host suites | 163 pass, 0.24 seconds |
| Main 082 audit fixture repair | root54 pass / independent54 pass |
| Final full regression | 1982 pass, 60.95 seconds |
| Ruff across src/tests and new validation scripts | pass |
| Specify prerequisites and git diff whitespace checks | pass |

Independent review caught directory case/Unicode aliases and partial directory-FD ownership;
root review added concurrent single-use transitions and verified close-number reuse behavior.
Eight path-alias tests failed before the identity fix. The FD reuse and signed-int64 minimum
clock regressions each failed before their respective fixes and now pass.

The first full regression returned1981 passed / 1 failed in52.08 seconds. A main-checkout082 test
assumed today's package was still the original38-file package; its assertion failed before any
live-source audit call. The repaired test reconstructs the pinned082 Git blobs in a temporary
fixture and checks only that fixture. It keeps the38-file set, original blob identities, and missing
HTTP-helper rejection after rehashing. No historical helper, manifest, result or seal was edited.

Commands used for the broad checks:

```sh
.venv/bin/python -m pytest -o addopts='' -q --tb=short
.venv/bin/ruff check src tests specs/083-host-execution-guard/validation
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Local native observations

`native-smoke.json` binds its implementation, tests and reproducer. Normal/exceptional explicit
cleanup left no assertion at the queried ID. A bounded child test held one matching assertion,
exited via `os._exit(0)`, was reaped, and had zero matching assertions at the next checks. This
is local ordinary process-exit evidence, not a SIGKILL, crash, actual-sleep or cross-platform test.

`native-scope/result.json` binds the public-scope reproducer, three product files and two original
three-line journals. One scope returned and one raised a fixed exception. Both were queried after
exit with no remaining assertion. Its `scope_cleanup_completed` field describes observed scope
exit and assertion cleanup, not proof of final journal fsync on the exceptional-body path: preserving
that original exception can hide a secondary cleanup error. A readable record cannot prove its own
fsync returned. Full persistence requires a successful scope return, or separately instrumented
cleanup evidence; the smoke does not claim the latter for the exceptional-body path.

No model, external provider, company platform, WebAgent or real candidate was executed by these
native checks. No actual system sleep or permanent setting change was requested. Ordinary unit
regressions retain their existing local fixture/loopback behavior.

## Preserved evidence and scope limits

`seal-verification.json` compares static Git blob identities and complete tracked file sets:
074/076/078/082 preserve68/105/205/217 files respectively. Ignored Python caches are outside those
Git seals and were left alone. No old campaign live-source audit was run against changed product
code. Independent review and result/artifact hashes are recorded alongside this document.

The policy permits display sleep and cannot prevent lid-close, explicit or low-battery sleep, or
establish effectiveness during Dark Wake. Property checks are point-in-time observations. Clock
divergence includes wall-clock adjustments and sampling uncertainty; it is not exact sleep time.
Existing directory identities handle macOS aliases; missing names are compared conservatively and
can reject separate future spellings on case-sensitive storage. Failed descriptor close is uncertain
and is never retried using a potentially reused numeric descriptor.

This feature did not launch a new evaluation. Sealed082 remains staged valid0/2; failed scores and
complete usage/cost stay null. The next design should separately address per-request time limits
and bounded transport recovery, with shared deadlines, physical-attempt counting and unknown-usage
accounting, before a fresh GLM-5.2 measurement registration.
