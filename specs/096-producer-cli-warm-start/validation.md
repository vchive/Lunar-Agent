# Validation — 2026-09-14

## Results

- CLI and shared preparation tests were first run before implementation and failed for the missing
  command/API. The implemented producer preparation/export/import modules initially passed all
  66 tests in 2.06s; the legacy and new CLI checks passed 78 tests in 9.43s.
- Producer/Shinka/remote-material/seed compatibility checks: 146 passed in 0.37s.
- First full regression: 3829 passed, 1 failed in 254.39s. The existing stable evidence export
  fixture retained SQLite connections until garbage collection. Collecting them during the
  diagnostic's second snapshot changed DB/WAL/SHM files and correctly returned
  `diagnostic_database_changed`, surfaced by export as `materialization_evidence_source_unavailable`.
  A controlled GC probe reproduced this; collecting after materialization and before sampling
  produced stable snapshots and a successful export. The evidence bundle fixture now settles
  those connections before inspection, matching the existing diagnostic test pattern. Product
  snapshot checks and assertions were not relaxed. Bundle/diagnostic/snapshot checks after this
  fixture fix: 149 passed in 25.59s.
- Independent CLI review found that duplicate material identity can raise `SeedAdmissionError`
  during preparation, before controller exception handling. A new test first reproduced the
  uncaught exception; CLI now returns the fixed `duplicate_identity` JSON error and exit code 2
  before creating a run or executing commands. Public admission API exceptions are unchanged.
- Final producer preparation/export/import plus existing CLI checks: 127 passed in 9.29s.
  Feature 096 adds 43 cases (12 API, 19 CLI, 12 integration); counts above overlap.
- Second full regression: 3829 passed, 2 failed in 238.59s. Two existing loopback HTTP runtime
  tests received a generic transport failure instead of their expected HTTP 500/malformed JSON
  response. Both passed unchanged in a targeted rerun (2 passed in 1.81s). The original output
  did not retain the transport reason/cause, so it does not establish a specific cause.
  A bounded diagnostic probe over the runtime module passed all 29 tests in 14.71s; ordinary
  loopback exchanges took 0.094–0.136s, and only the explicit 0.01s case timed out as expected.
  The full-run failure was not reproduced. Runtime/transport code and these tests remain unchanged.
- Final full regression: **3831 passed in 544.73s**.
- Final Ruff, compileall, offline wheel/sdist build, Specify prerequisites and diff check: passed.
- All 601 tracked files in Feature 051/074/076/078/082 match pre-feature commit `19321ca`.
- Independent API, CLI/integration and documentation reviews completed; reported issues addressed.

## Behaviors exercised

- Standalone export dispatches before normal home/config/Store initialization and never runs an
  evaluator, producer or scheduler. Bounded contract reads return fixed errors for invalid JSON,
  duplicate keys, oversized files and unsafe nodes. Export failures preserve fixed exporter codes.
- Ordered/repeated explicit program IDs and top-k selection are mutually exclusive. Default
  convenience selection remains one producer-correct row. An export response describes material
  and digests without granting admission or score authority.
- Producer input is population-only, mutually exclusive with a seed manifest and seed identity
  overrides, and requires an explicit producer fingerprint and command-backed local exact evaluator.
  The optional producer name adds a separate pin. Orphan pins and invalid combinations fail early.
- Shared preparation checks envelope/material/contract/pins and constructs an unadmitted manifest
  in memory. Existing file/object admission APIs retain validation order, reference overrides and
  single evaluation. Changed material between preparation and admission fails before evaluation.
- Native Shinka SQLite fixture with externally scored good/bad candidates exports and enters the
  regular controller seed path. The local evaluator admits the good seed with score 0.42, rejects
  the bad seed, and never trusts external scores 9999/10000 or producer correctness. Seed generation
  and iteration remain zero, lineage is retained, and external evidence is reduced to digests.
- An all-invalid batch fails before population search. Resume re-evaluates seeds, preserves IDs and
  admission events, and does not replay a completed generator. Source, producer identity, evaluator
  command and envelope budget/run identity drift are rejected without corrupting canonical state.
- Detached startup forwards the original producer root and pins; the normal child resumes from
  those inputs. It receives no synthetic seed file or seed identity flags.

## Scope and retained limits

All executions were offline fixture programs and local tests. No real model, provider, WebAgent,
OpenEvolve/ShinkaEvolve service, remote campaign or algorithm effectiveness measurement ran.
This feature exposes completed local single-file producer material through CLI; it does not add a
live runner, network synchronization, repository/workflow candidates or a benchmark comparison.
The dependency digest describes the source bundle and the environment digest describes the declared
protocol; neither verifies an external runtime installation or transitive dependencies. External
producer claims still need local exact evaluation. No effectiveness or WebAgent parity claim follows.
