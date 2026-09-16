# Feature 110 validation

Date: 2026-09-16. All workers and candidate/evaluator processes in validation are local fixtures.
No real provider, external evolution framework or new effectiveness campaign is run.

## Acceptance checks

- Complete two-file Agent proposals enter the existing population pipeline; helper-only changes
  affect bundle identity and independent selection while entrypoint bytes stay unchanged.
- Complete parent source and pinned inputs are staged in a new workspace; bounded prompts retain
  references to large context. Evaluator implementation is absent from the staged solver context.
- Direct command Agent JSON preserves every file and ambiguous/duplicate fields for strict bundle
  validation. Legacy adapter and single-file generation behavior remain compatible.
- CLI command/Agent/native-runtime selection validates options before home/Store or generation.
  Native subprocess workers exercise the runtime path; model/tool-loop wiring uses an offline
  fixture. Mode/configuration changes cannot reuse an existing run's generation identity.
- Controller delivery retains selected complete source and independently scored outputs. Terminal
  resume does not increase Agent or candidate invocation counts; context drift prevents generation.

The standalone quickstart command ran unchanged with exit code 0. Its native subprocess worker
read complete parent context and generated four scores `1, 2, 6, 7`; all bundles had distinct
identities with unchanged entrypoint bytes. The selected helper/output/report passed pinned delivery
inspection. Terminal resume kept Agent and candidate invocation counts at `4 → 4`. Log:
`/private/tmp/lunar110-quickstart.log`.

Focused acceptance includes 32 generation-context/parser cases, 35 CLI cases, 4 direct Agent
transport cases and 3 independent controller/runtime integration cases. The large-context case
retains all 42 parent files through prompt compaction. Other cases exercise source/input/harness,
record/receipt/evaluation drift; malformed/duplicate/oversized responses; fresh workspace allocation;
relative CLI workspace; mode mismatch; and interruption preservation across a simultaneous close
failure. Existing Agent and CLI regressions also passed before the full run.

After product freeze, the complete suite passed: **5187 passed, 1 skipped in 284.75s**.
JUnit confirms 5188 tests, zero failures and zero errors, including all 74 new cases. The existing
case-alias test skips on this case-sensitive filesystem. Logs: `/private/tmp/lunar110-full.log` and
`/private/tmp/lunar110-full.xml`. No product changes followed the full run.

Also passed: all-src/tests and quickstart Ruff, compileall, Specify prerequisites with tasks,
installed CLI help, updated document links and `git diff --check`. Frozen `specs/051*`, `074*`,
`076*`, `078*` and `082*` have no changes relative to `027a235`.

## Scope

This extends explicit `evolve-bundle` and Agent generation. Evaluator preparation, normal solve
routing, parent-run delivery/recovery, external bundle seed imports and real model effectiveness
remain separate work. Agent response text remains bounded to 1 MiB; full bundle capacity is not
silently exposed as an unbounded model response. The local execution/context boundary is not an
OS sandbox or authentication of host dependencies.

Existing verified work through `d863df6` (40 accumulated commits) was pushed successfully to
`origin/main` at the user's explicit request. Subsequent completed verified changes are also pushed;
historical instructions to keep commits local are superseded. Frozen measurement files remain unchanged.
