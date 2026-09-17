# Validation

## Implemented boundary

The product change adds one pure illustrative request helper and modifies only the shared
snapshot invocation prompt. An AST comparison against 5560eb9 confirms no other existing product
definition changed. Both legacy candidate-mode compiler/auditor prompts remain byte-identical
for the same fixture context. Request construction, validators, process/model settings, source
restrictions, frozen identities and recovery behavior remain unchanged.

The example uses native input/evaluator serializers, an explicitly illustrative interpreter path,
and one empty contract placeholder that expands to the actual canonical contract at runtime.
Task contract/profile text still appears once per prompt. Snapshot instructions distinguish input
target from contract/profile/probe paths and output paths, including absent optional outputs and
zero-byte input files. The shared instruction grows from 1,079 to 5,329 UTF-8 bytes; this is increased
protocol specificity, not evidence of improved request latency or a more successful model response.

## Local validation

- **8 new tests passed in 0.800s**: compiler/auditor examples expanded through the native request
  parser; six real compiler/auditor probe processes; fresh independent target-versus-path failure
  fixture; two actual recorded candidate/evaluator executions with UTF-8 and zero-byte input.
  Requests match advertised field names/types, preserve nested paths and omit optional output files
  while retaining their descriptors. Validity and exact scores are checked, not just schema keys.
- **88 existing related tests passed in 14.933s**, covering protocol examples, snapshot preflight,
  production evaluation and source-aware pipeline. Both JUnit reports have zero failures/errors.
- The 112 quickstart selects 7 from 1/2/6/7. Terminal resume keeps compiler/evaluator-compiler/
  auditor/Agent/candidate calls at **1/1/1/4/4** and exactly one delivery copy.
- Independent product/test review found no blocking issue. Ruff and Specify prerequisite checks
  passed before freezing implementation. The full regression exposed the historical fixture
  prerequisite described below; the product and its eight tests remained unchanged.

## Regression isolation

The original unfiltered command completed **6286 passed, 1 skipped, 24 errors in 427.95s**.
All 24 errors are setup failures in the original `registered` fixture: it explicitly requires
519fea5 product bytes and raises `product_changed` on the modified evaluator prompt. There were
zero assertion failures. Keep this original result; it is not an all-green current-product suite.

All 24 original nodes then passed in **12.33s** inside a detached 5560eb9 checkout, with all 160
registered product/measurement/history pins and the frozen famou import location verified. Its
src/pyproject bytes equal the registered 519fea5 product; the temporary worktree was removed.
Only temporary fixture manifests were prepared/verified, never the original registration or slot.

`tools/run_tests.py` makes this split explicit and repeatable. It verifies the fixed commit/manifest,
registered bytes, exact 24-node collection, current and frozen import locations, and JUnit counts.
It runs current tests on current code and the same 24 original nodes on the frozen checkout; either
phase or cleanup failure fails the entry point. No version-specific skip/xfail or guard override is
introduced, and it invokes no campaign CLI or network request. CI fetches history and invokes this
entry point; README documents the boundary.

The runner adds **18 passing tests in 3.413s**, including real detached worktrees, exact original
fixture-node collection, byte drift rejection, inherited import/filter isolation, real pytest
success/failure/skip/count handling, both-phase exit propagation and worktree cleanup.

## Final full verification

Command: `.venv/bin/python tools/run_tests.py --junit-dir /private/tmp/lunar124-regression`.
The entry point returned exit 0 and removed its temporary worktree.

- Current working tree: **6304 passed, 1 skipped, 24 deselected in 418.44s**. JUnit records
  6305 tests with zero failures/errors. Only the exact frozen-version nodes are deselected here.
- Frozen 5560eb9 checkout (product 519fea5): **24 passed in 15.30s**. JUnit records exactly
  24 tests, zero skips/failures/errors. Every deselected node runs unchanged in this phase.
- All five frozen implementation/test/CI files retain their hashes. The product prompt and its
  eight tests remained unchanged across both full runs; the runner/18 tests/CI were added after
  the first run exposed the version-bound fixture prerequisite.
- Independent product, integration-test and regression-runner reviews passed. Ruff across src,
  tests and tools, compileall, installed CLI help, Specify and whitespace checks passed. All 135
  local links in the nine updated Markdown files resolve. Historical bytes were rechecked after
  the initial full run and isolated historical tests, with the same results below.

These are two explicit test environments, not a claim that all historical tests passed on changed
product bytes. The first unfiltered run and its 24 setup errors remain recorded above. Completed
work is ready for the authorized normal commit/push.

## Historical preservation

Independent read-only audit matched all 73 tracked spec files for 113/115/117/120/123 and 17 related
measurement tests against 5560eb9. The 123 manifest matches both HEAD and preregistration 034b184;
69 historical and 14 measurement pins match current bytes. All 77 registered product pins match
519fea5 Git objects; current product differs only in the expected evaluator prompt file.

The 123 retained inventory matches all **15/15** files by size/SHA; the 120 inventory matches
**46/46**. Inventory SHA256 values are respectively
`b560dc4a1beb69e688a7e4a75ac080cc0d20f3c351322df836fa0f17da4275c7` and
`4183a2c452a70216042f8522c5ce255b62ae826fe070283f6ff0e6d552c1fa0f`.
The audit itself did not execute a campaign verifier/pinner, generated source or model request.
Historical registration tests only use temporary manifests in the isolated checkout.

There is no new real-model result. 113/115/117/120 remain separately 0/2; 123 remains 0/1.
This independently built local fixture does not replay or repair 123. A follow-up diagnostic needs
separate fixed registration committed and pushed before any real requests; complete multi-file
delivery, external producer search and effects on latency/quality remain unverified.

## Local logs

`/private/tmp/lunar124-request-protocol.xml`, `/private/tmp/lunar124-existing.log/.xml`,
`/private/tmp/lunar124-quickstart.log`, `/private/tmp/lunar124-scope.json`,
`/private/tmp/lunar124-freeze.json`, `/private/tmp/lunar124-history.py/.json`,
`/private/tmp/lunar124-full.log/.xml`, `/private/tmp/lunar124-frozen-tests.log/.xml`,
`/private/tmp/lunar124-version-bound-tests.json`, `/private/tmp/lunar124-regression-runner.xml`,
`/private/tmp/lunar124-regression.log`, `/private/tmp/lunar124-regression/current.xml`,
`/private/tmp/lunar124-regression/frozen123.xml`, `/private/tmp/lunar124-doc-links.json`.
These are local validation logs, not measurement artifacts.
