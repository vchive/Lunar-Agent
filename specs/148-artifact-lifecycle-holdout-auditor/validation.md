# Validation: artifact/lifecycle and holdout receipt auditor

**Status**: Implementation and validation complete
**Validation mode**: provider-free; auditing is read-only and launches no campaign

Feature 148 is implemented as a Python API over the existing native validators. Its request,
SQLite/WAL snapshot, generation/artifact bindings, one-slot identity, lifecycle ordering and eight
holdout receipts are covered by offline tests. Audits do not execute candidate source, an evaluator
or a holdout. Existing shared/full regression fixtures include ordinary local execution and
callbacks; their test success is not a real-model acceptance result.

## Final focused verification

The nine suites in [quickstart.md](quickstart.md) passed **422 tests** after the final budget-binding
and SQLite fixture fixes. These counts partition the selection:

| Suite | Passed |
| --- | ---: |
| Audit request | 189 |
| SQLite snapshot | 18 |
| Parent lifecycle | 23 |
| Execution slots | 19 |
| Holdout audit | 55 |
| Combined/native adapter | 78 |
| Combined snapshot | 4 |
| Native evidence | 11 |
| Read-only delivery | 25 |

The final command used `-o addopts= -q --disable-warnings` and wrote
`.lunar-evolution/test-results/feature148-final/focused-final.xml` and `focused-final.log`.
Shared Feature 147 observer/generation/inventory checks separately passed **58 tests**.

Independent review fixed two product issues: native delivery inspection could implicitly recover an
archive, and preparation policy values were not compared to the manifest's exact 600/900/1,860-second
budgets. Read-only archive/strategy construction now rejects recovery state and write entry points,
and missing/mismatched preparation budgets cannot verify the boundary.

An intermediate selection reported **420 passed, 1 failed**. Its source-immutability fixture allowed
the last SQLite writer connection to be garbage-collected during the audit, triggering a real WAL
checkpoint. A deterministic cyclic-connection/forced-GC test reproduced the cause and confirmed that
the product correctly rejects it. The fixture now retains writers until teardown; the read-only success
case also forces GC. Product snapshot checks were not relaxed. The original `focused.log` and
`focused.xml` remain alongside the passing final result. The 76 temporary-directory cleanup warnings
come from pre-existing local pytest directories and are not test failures.

## Complete regression checkpoint

The complete three-stage command is:

```sh
.venv/bin/python tools/run_tests.py --junit-dir .lunar-evolution/test-results/feature148-final
```

The current-product phase passed **7146 tests, 1 skipped**, with zero failures/errors. The archived
historical phase passed **2294 tests** and the frozen registration phase passed **24 tests**; all
three phases completed with zero failures/errors. This run
collected before the last six slot cases, 46 adapter cases and one GC reproduction were added; its
JUnit records 13 slot, 32 adapter and 17 snapshot cases. The final budget-binding and fixture changes
are verified by the 422-test selection above. Historical and frozen phases are recorded when complete
in `pytest.log`, `archived.xml` and `frozen123.xml`; no arithmetic projection is used as an executed
count. The runner exited 0 and retained `current.xml`, `archived.xml`, `frozen123.xml` and `pytest.log`.

Ruff for `src tests tools`, compileall and `git diff --check` pass. SDD path resolution used
`--paths-only --json`, all five feature documents exist and `.specify/feature.json` is unchanged.
The current tracked and nonignored untracked file/path scan found no retired project name. GitHub Actions
[Run 227](https://github.com/vchive/Lunar-Evolution/actions/runs/35712084794) confirms the preceding
`e0bf8dc` observer checkpoint, not this implementation.

## Evidence and limits

At the Feature 148 checkpoint, the native execution record had no independent cleanup observation.
That checkpoint therefore classified an otherwise successful retained execution as `unverifiable`
with `execution_cleanup_unknown`; a copied native execution/evaluation directory also remained
unverifiable. Feature 149 now adds the optional cleanup-v1 receipt and wires it into native
execution and acceptance auditing: a fresh record with a verified receipt can pass the execution
boundary, while a legacy three-file record without `cleanup.json` remains `execution_cleanup_unknown`.
Missing, failed, or relocated evidence still cannot be repaired by later receipts or successful
holdouts. Request/token ceilings are digest-bound declarations, while actual usage accounting and
launch enforcement belong to the separate measurement implementation.

The combined report always emits `provider_called_during_audit=false`, `executed_during_audit=false`,
`mutated_during_audit=false` and `real_acceptance_claimed=false`. Its three compatibility counters
remain `0/1`; they do not rewrite historical results. Feature 139 remains preparation `1/1`,
primary/joint `0/1`; Feature 131/134/139 retained evidence is untouched. No provider, real campaign
or WebAgent was run, and no historical generated source was executed. A separately committed launch
preflight/registration seal and the actual registered automatic multi-file end-to-end acceptance are
still required; Feature 149's provider-free cleanup implementation does not authorize either step.
