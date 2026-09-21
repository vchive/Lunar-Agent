# Feature 145 validation

## Identity and compatibility

The product is Lunar Evolution. The distribution and sole console command are `lunar-evolution`,
the Python package is `lunar_evolution`, user configuration uses `LUNAR_EVOLUTION_`, and fresh state
defaults to `.lunar-evolution`. Explicit `--home` retains precedence. Detached launches, public
exports, prompts, HTTP identification, profile identity, and protocol domains use the new namespace.
The reference-benchmark API is `benchmark_case_content_digest`; its `lunar-evolution-case-v1`
domain intentionally produces a different identity from the earlier domain.

No old-name alias, encoded spelling, configuration fallback, state merge, database rewrite, or
automatic run resumption is introduced. Existing execution-only `LUNAR_*` variables keep their
meaning. External engines and benchmarks remain external references with accurate attribution.
The user renamed the GitHub repository; origin now points to `vchive/Lunar-Evolution`.

## Preservation

The [public archive index](../../docs/history-archive.json) records **844 files / 5235354 bytes**
at `c6947fdfbf43d84e83cc29cc215e7bc0250db83a`. It matches the inventory collected before
migration exactly. These sealed files were retired from the current publication tree; their
original Git blobs and history were not altered. The source archive contains all **1973 original
Git blobs**, independently checked without differences. Its whole-file SHA-256 is
`ff9a3d8551e145940bd1a47000262d247883718404c7fd8e566aa1939d0611ba`.

Private local evidence, previous state/environment/cache/build metadata and the source archive are
preserved outside the checkout at:

`/Users/liminghan/Documents/lunar-evolution-archive/20260921-identity-c6947fd`

Read-only rechecks of the relocated Feature 131/134/139 inventories matched all **21 / 97 / 70
files**, **155485 / 327394 / 298462 bytes**, and every original size and SHA-256, with no missing
or extra files. The report is `validation-145/archive-integrity.json` below that external archive.
This proves preservation of file contents, not inode preservation or resumability. Ordinary CLI
use of `--home` may initialize selected state; it is not a read-only archive inspection method.

## Verification

- Isolated wheel installation: **5 passed**. A separate environment outside the checkout, with
  no repository PYTHONPATH, exercised imports, sole CLI/module entrypoints, configuration and
  explicit-home precedence, the new digest domain, mock run/status/events, and actual detached
  mock execution. A stale build directory initially contaminated the wheel; preserving it outside
  the checkout and rebuilding resolved the failure without adding a compatibility package.
- Regression runner: **34 passed**. Coverage includes the actual offline historical installation
  and console launcher, exact archive inventories, import isolation, original registration pins,
  report checking and cleanup.
- Focused CLI/effect suites: **146 passed**.
- Independent reviews covered namespace/API migration, clean packaging, existing-state limits,
  archived test isolation, exact test denominators, and pre/post historical integrity checks.
- Full three-phase regression and final static/name/link/SDD results are being recorded below
  after the active run finishes. No passing full-run result is claimed yet.

### Initial full-run findings

The initial runner completed all phases and correctly returned failure: current **6573 passed,
2 failed, 1 skipped** in 507.28s; archived **2293 passed, 1 failed, 24 deselected** in 246.79s;
frozen123 **24 passed** in 20.64s. Original XML/logs remain under `validation-145/` in the external
archive and are not overwritten by follow-up checks.

The two current failures were prompt snapshot expectations still containing the pre-migration
native system-message digests. Restoring only the earlier product name reproduces all four original
hashes; budget guidance, custom-system hashes and tool schemas are unchanged. Updating the four
current native golden values resolved these failures; the complete file and related envelope
integration suite passed **31 tests**.

Source inspection identifies an existing race consistent with the historical failure in the fixed
Feature 139 observation helper, `test_preparation_ceiling_does_not_leak_between_threads`.
Two threads can observe the shared
transport-file-created flag as false outside the ledger lock, then both use exclusive file creation.
One diagnostic append is rejected while both ledger requests complete. This is not caused by the
new package import path. The archive source, tests and integrity checks remain unchanged; the
failure is retained explicitly, and a separate complete historical recheck is reported separately.
Passing a later run does not establish that this historical race was repaired. The test traceback
confirms two successful ledger requests and a missing diagnostic row; the swallowed exception
itself was not captured, so the file-creation race is a source-based diagnosis.
One separate complete historical recheck passed **2294 tests, 24 deferred, 0 skipped** in 255.39s;
all original file and registration pins passed before and after execution. Its separate reports
are `archived-final.xml`, `archived-final.log`, and `archived-final-summary.json`. The first failure
and source-based analysis remain in `archived-observer-race.json`; no retries are built into CI.

The next full current pass of the suite reported **6574 passed, 1 failed, 1 skipped** in 531.14s.
The remaining failure was missing release after a subprocess timeout, not a failed namespace
assertion. A separate deterministic real-process test established a cleanup race at the boundary
between reaping and publishing `Popen.returncode`. The minimal repair and **228 passing related
tests** are documented in [142 validation](../142-automatic-solve-lifecycle/validation.md).
Three permanent tests reproduce the race and retain refusal when the owned group still exists.
This independent reproduction does not by itself prove the timeout failure's exact interleaving;
a subsequent diagnostic reproduction instead observed transient `PermissionError` during the
owned process group's termination. That observation must never be treated as proof of absence.
The prematurely started `current-post-cleanup` full check was stopped when this additional cause
was identified; it is not a passing result. The final unmodified full-suite check follows the
bounded repair documented in Feature 142. Both repairs passed **235 related tests** and **100
real timeout plus 100 real cancellation repetitions**, retaining the original release assertions.
The seven probe-permission cases initially gave **3 failures / 4 passes** before the second repair;
all seven then passed, including persistent denial and permission-boundary refusals.

The original baseline collected **8873 tests**: 8848 passed, one existing skip, and 24 deferred
registration tests. Retiring 2318 historical nodes leaves 6555 current nodes. Sixteen additional
runner checks, five installation checks and ten cleanup-race cases give **6586 current nodes**;
historical execution is still **2294 + 24**. Thus the total required inventory is **8904**,
a net increase of 31, with no
historical test dropped. The archive runner checks the exact 2318-node collection digest and the
original registration manifest's 77 product / 14 measurement / 69 historical pins before and after
execution.

## Scope limits

No provider request, WebAgent rerun, new campaign, or historical generated-code execution was
performed. Historical 139 remains preparation **1/1**, primary/joint **0/1**. Naming migration does
not close the outstanding real-model complete-delivery acceptance, Feature 142 Phase C automatic
background entrypoints, or Feature 143 T009 worker-consumer integration.
