# Validation

## Current status

Specification-only checkpoint dated 2026-09-20. Product implementation has not started. No Feature
142 product test or implementation acceptance criterion has been claimed as passing. The
read-only inspection used to write this design is not runtime or regression evidence.

Only `spec.md`, `plan.md`, `tasks.md`, and this validation record are in scope for this checkpoint.
No `src` file, Feature 139 file, retained historical evidence, provider configuration, real
registration, or campaign root is changed or executed by this specification work.

## Completed document checks

- Specify prerequisites passed with `--require-tasks --include-tasks` for this feature directory.
- The four expected Markdown files are present, and both local document links resolve.
- The task list has two completed specification/read-only inspection items and 23 open
  implementation/verification/completion items.
- `git diff --check` passed at the specification checkpoint.

These are document checks only. They do not close any product acceptance row below.

## Planned acceptance matrix

| Area | Required offline evidence | Status |
| --- | --- | --- |
| CLI validation | Valid bounds; zero/negative/bool/non-finite/malformed/out-of-range rejection; all unsupported modes rejected before side effects | Not run |
| Persistence | Explicit policy and lifecycle marker; exact restore/match; no legacy policy injection; secrets excluded | Not run |
| Shared deadline | One deterministic clock across intake, preparation, generation, execution, scoring, selection, and delivery; tighter local ceilings honored | Not run |
| Exhaustion | Before claim/request/process, after late result, and before publication; one terminal event; no new work on continuation | Not run |
| Parent lifecycle | Parent remains active while child runs; only verified delivery completes orchestration; ordinary scheduler cannot claim control task | Not run |
| Recovery | Awaiting-input/answer, admissible preparation recovery, interrupted nonterminal ownership, successful/cancelled/exhausted terminal idempotency | Not run |
| Identity preservation | Byte/digest equality for input, profile, contract, evaluator, source, execution admission/plan; separate truthful effective-timeout observation | Not run |
| Cancellation | Every phase; reciprocal child binding; unrelated run untouched; late result rejection; cancellation/deadline winner retained | Not run |
| Local cleanup | All owned probe/candidate/evaluator groups reaped; callback failure does not stop fan-out; coordinating worker cleaned last | Not run |
| Detached gate | Automatic detach remains rejected until local cleanup acceptance passes | Not run |
| Detached behavior | Fresh/resumed/answered background runs; exact policy; secret-free argv; one owner; status/cancel; all exit paths clear ownership | Not run |
| Compatibility | Existing 133/137/141, CLI, Controller, preparation, process, generation receipt, execution/evaluation, and delivery regressions | Not run |
| Full regression | Current full offline suite and fixed historical stage, with exact counts and report paths | Not run |
| Historical evidence | Exact retained Feature 131/134 file sets, sizes, and hashes; no Feature 139 rewrite or provider activity | Not run |

## Test design rules

Use injectable monotonic clocks for deadline ordering and fresh local fixture programs for actual
process termination. Fake the provider transport while keeping native CLI, Controller, Store,
generation, execution, scoring, and delivery paths real where integration needs to be established.
Never execute retained provider-generated historical source as a regression fixture.

Check configured and effective timeouts independently: a request-level 600-second ceiling, a
900-second preparation ceiling, and a smaller solve remainder must produce the minimum applicable
value without rewriting any frozen policy or input. Exhaustion observed after local work may
retain bounded diagnostic materials but cannot authorize the next stage or parent success.

Distinguish active-execution scope from cumulative lifetime. An awaiting-input or admissible
nonterminal continuation obtains a new execution identity under the unchanged policy; tests must
not falsely assert that the sum of those executions is bounded by one allowance. Conversely, an
observed solve-budget terminal failure must never regain an allowance through any continuation.

Before enabling detach, run real local process fixtures that exercise independent subprocess
groups, including children with open output pipes and cleanup callbacks that raise. Assert their
owned PIDs/groups are gone or reaped before the coordinator is reported cleaned up. No provider
side cancellation or completion claim can be inferred from these local tests.

## Planned verification commands

The focused file list will be filled in after implementation; do not treat an empty placeholder
suite as completed validation. Existing preparation/Controller/process/delivery suites and new
native lifecycle integration tests are required, followed by:

```sh
.venv/bin/ruff check src tests specs/142-automatic-solve-lifecycle
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY=specs/142-automatic-solve-lifecycle \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature142
```

Also verify local Markdown links and compare historical inventories with the retained authorities.
Record exact test counts, skips, elapsed time, report locations, and independent review findings
here when those checks actually run. Specifications can pass structural checks before product
implementation; such results must be labelled document checks and must not close implementation
tasks or the detached cleanup gate.

## Release boundary

Passing offline tests would establish automatic lifecycle behavior, local deadlines, and local
cleanup only. It would not establish evaluator quality, provider completion, current-model task
success, WebAgent parity, or completion of Feature 139's independent real acceptance. This feature
does not introduce a new attestation or user-confirmation step for routine product development.
