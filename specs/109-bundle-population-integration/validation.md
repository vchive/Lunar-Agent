# Feature 109 validation

Date: 2026-09-16. Local subprocess fixtures only; no model/provider, external framework or new
effectiveness measurement. Product changes extend the existing population/archive/controller seams.

## Acceptance evidence

- A real two-file candidate keeps its entrypoint constant and changes only its helper. Four locally
  evaluated reports score `1, 2, 0, 9`; the out-of-bounds proposal's high self-reported score is
  ignored, and the valid 9-point candidate wins. Each has a separate bundle and execution identity.
- Existing lineage, generation, validity-first ranking and offspring journals work with v2 receipts.
  A larger two-island fixture exercises actual migration; the two-member fixture correctly preserves
  each island's last member under the existing migration policy.
- Terminal strategy/controller/CLI resume validates retained evidence and does not rerun the
  generator, candidate or evaluator. Changed source, snapshot, plan/admission/completion, report,
  receipt or Store-bound selection is rejected before new work or delivery allocation.
- Profile/harness and shallow-frozen contract mutation after strategy construction are rejected
  before source staging and process launch. One execution/evaluation cannot register two IDs.
- Process failures retain attempt directories and failure outcomes without inventing scores.
  Known publication failure retains the already evaluated attempt and a new try uses a fresh root.
  Archive/rollback durability uncertainty retains source, sidecars and evaluation evidence and
  propagates the existing publication-unknown condition.
- Controller delivery verifies canonical selection, Store rows and events, then copies complete
  source, scored outputs, inputs, contract and evaluator materials. Inspection detects changed,
  missing, extra or symlinked files without running code. Full 165-file delivery with long paths
  exceeds 128 KiB of manifest and roundtrips successfully; over-cap materials fail before allocation.
  A completed run with recoverable candidate failures still delivers its valid selected result while
  preserving the error and outcome journal. Simultaneous close failure cannot mask an interrupt.
- Single-file v1 receipt digest has a frozen golden assertion; old Candidate serialization and
  command request shapes are preserved. Existing single-file/seed materialization does not silently
  discard helper files.

The [quickstart](quickstart.md) shell block was extracted unchanged and executed under `zsh` with
the installed project. It produced four scores `1, 2, 6, 7`, exercised complete parent source
context, delivered the 7-point result, passed pinned inspection and retained invocation counts
`candidate: 4 → 4; generator: 4 → 4` across terminal resume. The inspection home was not created.
The resulting delivery was also copied to a separate temporary root and inspected with its original
saved digest; the relocated copy passed with unchanged selected helper and report bytes.

## Regression results

After product freeze, the complete suite passed: **5113 passed, 1 skipped in 277.57s**.
JUnit confirms 5114 collected tests, zero failures and zero errors. The existing case-alias test
skips on this case-sensitive filesystem. Logs: `/private/tmp/lunar109-full.log` and
`/private/tmp/lunar109-full.xml`.

All 100 new cases are included in that run: 44 candidate/model compatibility, 7 pipeline integrity,
11 population, 22 controller/delivery and 16 CLI cases. No product changes followed the full run.

Also passed:

- `ruff check src tests` and `python -m compileall -q src tests`;
- Specify prerequisite check with `--require-tasks --include-tasks`;
- installed `lunar-evolution evolve-bundle --help`, all six new package exports, and the executable
  quickstart with relocated-delivery inspection;
- `git diff --check` and updated readiness/validation document links;
- zero changes relative to `027a235` under frozen `specs/051*`, `074*`, `076*`, `078*`, `082*`.

## Scope and remaining work

Output bytes are evaluation-time snapshots, not process-exit proofs. Supplied evaluator code and
configuration are pinned; interpreter/dependency authenticity and OS isolation are unchanged.
Local fixture scores establish integration behavior, not current-version model effectiveness.

This explicit local bundle mode does not yet extend automatic Agent generation, default task
routing, parent-run automatic delivery or generic OpenEvolve/Shinka SeedManifest import. Broader
active cancellation/recovery orchestration and independently registered real measurements remain.
Frozen historical measurement directories must remain unchanged. Commit locally only; do not push.
