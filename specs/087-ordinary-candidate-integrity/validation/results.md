# Feature 087 validation

Completed on 2026-09-14 on the local macOS host. The feature adds canonical integrity receipts,
publication checks, and fail-closed resume validation for ordinary population candidates. It does
not start a model, provider, external evolution framework, WebAgent, remote service, scheduler, or
campaign.

## Verification

| Check | Result |
| --- | --- |
| Ordinary candidate/controller/evolution focused suites | 212 passed in 3.69 seconds |
| Controller failure-path and ledger regression | 15 passed |
| Full repository regression | 2408 passed in 65.02 seconds |
| Ruff (`src/lunar_evolution`, related tests) | pass |
| Python compileall (`src/lunar_evolution`, `tests`) | pass |
| Specify prerequisites with tasks | pass |
| `git diff --check` | pass |
| Sealed 074/076/078/082 trees | 595 tracked files unchanged |
| Independent final reviews | no remaining Feature 087 implementation or behavior blocker |

Commands used for the final checks:

```sh
.venv/bin/pytest -o addopts='' -q \
  tests/test_candidate_integrity.py \
  tests/test_controller_candidate_integrity.py \
  tests/test_evolution.py
.venv/bin/pytest -o addopts='' -q
.venv/bin/ruff check src/lunar_evolution tests/test_candidate_integrity.py \
  tests/test_controller_candidate_integrity.py tests/test_evolution.py
.venv/bin/python -m compileall -q src/lunar_evolution tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/087-ordinary-candidate-integrity" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

The focused suites cover canonical receipt round trips, source and optional execution snapshots,
authority/lineage/island/archive/outcome/state binding, legacy resume rejection, invalid active
population checks, append bounds, publication rollback, confirmed and unknown recovery, nested
report mutation, credential-shaped evaluator-kind rejection, required modern-state configuration,
fully rebound invalid-parent rejection, directory-entry replacement during rollback, process-group
cleanup, deterministic active/best/RNG/migration projection reconstruction, and idempotent
controller indexing. The expanded state matrix covers stagnation replay, exact numeric types,
projection-consistent statuses, legal partial-initialization cancellation and tied-seed recovery,
plus rejection when an outcome-binding group is stripped to mimic a legacy checkpoint. It also
includes a seeded failed-only first batch with no ordinary record, proving the ordinary marker is
retained and the outcome group cannot be stripped to replay the batch while that marker remains
visible. It also verifies that a
controller failure indexes only the exact ordinary archive prefix bound by the last durable state
digest and never indexes an uncommitted seed sidecar. Existing ledger rows with the same
`(path, kind)` key are all checked; conflicting digest or size evidence fails closed instead of
being hidden by the first row. Generic candidate indexing never publishes population seed
sidecars; verified seed evidence retains its separate commit gate.

## Limits and authority

The local evaluator remains the only score authority. This change creates integrity and recovery
evidence; it makes no effectiveness, valid-solution-rate, or WebAgent parity claim. It stores no
evaluator exception prose, credentials, prompt content, raw commands, or external score prose in
the ordinary receipt boundary.

A same-user process can still mutate a published path after the final in-process publication check.
A later resume rejects drift that did not also replace or recompute every hash-bound artifact
consistently. Receipts have no external signature or HMAC and do not provide authenticity against a
same-user process able to rewrite source, receipt, record, archive, and state as one coordinated
set. Parent-component validation and a later full-path `open()` retain a filesystem-level TOCTOU
window. The controller's failure-only safe prefix search hashes successive prefixes and is O(n²),
but it is not on the successful run path. If the initial candidate was published and the process
stopped before the first state write, resume returns the fixed
`ordinary_candidate_integrity_state_missing` error instead of inferring state.

Feature 087 begins when the first ordinary candidate transaction or pending batch adds the ordinary
integrity markers; a pure verified-seed checkpoint remains Feature 084 state. Population projection
replay depends on the current rank, trim, migration, and family-selection protocol, so a future
algorithm change must bump the integrity schema or explicitly migrate old state. The state file has
no independent signature/HMAC for arbitrary fields: structural status checks reject contradictions,
but a coordinated running/failed plus error rewrite for an empty `candidate_failed` initialization
is not distinguishable from the state alone. Unknown top-level fields outside the enumerated
authority, outcome, and population projections are not claimed as integrity-bearing evidence.
Likewise, coordinated deletion of the ordinary marker fields, the outcome/failed binding group, and
the journal leaves a seed-only archive indistinguishable from a genuine Feature 084 pre-ordinary
checkpoint. The failed-only replay protection applies while the modern marker remains visible.
