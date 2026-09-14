# Feature 085 validation

Completed and independently reviewed on 2026-09-14 on the local macOS host. New evolution
construction now defaults to `population`; `openevolve` remains an explicit material producer;
`loop` remains available only to historical readers and an importable non-mutating stub. External
material enters ranking or delivery only after Feature 084 admission and a current local
exact-evaluator receipt.

This validation did not start a model, provider, WebAgent, real OpenEvolve/ShinkaEvolve process,
remote service, company evaluator, scheduler, or campaign.

## Verification

| Check | Result |
| --- | --- |
| Feature 084 seed/backend dependency gate | 507 passed in 10.91 seconds |
| Feature 085 population/default/compatibility suites | 583 passed in 27.55 seconds |
| Full repository regression | 2673 passed in 78.26 seconds |
| Ruff (`src` and `tests`) | pass |
| Python compileall (`src` and `tests`) | pass |
| Feature 084 and 085 Specify prerequisites with tasks | pass |
| `git diff --check` | pass |
| Sealed 051/074/076/078/082 trees | 601 tracked files unchanged from `HEAD` |
| Independent final read-only review | no P0/P1/P2 implementation or behavior blocker |

Commands used for closure checks:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_seed_handoff.py \
  tests/test_remote_evolution.py \
  tests/test_openevolve_handoff.py \
  tests/test_remote_material_handoff.py \
  tests/test_producer_handoff.py \
  tests/test_evolution.py \
  tests/test_cli.py \
  tests/test_agent_evolution.py
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_seed_handoff.py tests/test_remote_evolution.py \
  tests/test_algorithm.py tests/test_evolution.py tests/test_cli.py \
  tests/test_population_defaults.py \
  tests/test_conversational_evolution.py tests/test_benchmark.py \
  tests/test_agent_loop.py tests/test_deep_effect_trial.py \
  tests/test_evolved_output_materialization.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/084-verified-seed-handoff" \
  bash .specify/scripts/bash/check-prerequisites.sh \
  --json --require-tasks --include-tasks
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/085-population-first-evolution" \
  bash .specify/scripts/bash/check-prerequisites.sh \
  --json --require-tasks --include-tasks
git diff --check
git ls-files specs/051-* specs/074-* specs/076-* specs/078-* specs/082-*
git diff --name-only HEAD -- \
  specs/051-* specs/074-* specs/076-* specs/078-* specs/082-*
```

The focused coverage verifies population defaults across contract, conversational, standalone,
and benchmark construction; early retirement of new or resumed loop execution; read-only legacy
parsing; verified-seed initialization and resume; distinct durable failure outcomes; exact local
re-evaluation of OpenEvolve material; independent benchmark adapters with one evaluator identity;
archive recovery before mutation; strict strategy-evidence JSON parsing; and materialization replay
guards. A missing terminal marker cannot cause a rerun when `execution.json` or
`.execution.json.tmp` exists as any filesystem node or cannot be inspected; the attempt, events,
and artifact ledger remain unchanged.

## Limits and deferred work

Feature 036 multi-output publication does not provide one transaction across filesystem output
promotion and SQLite artifact rows. If publication of the second output artifact fails, an earlier
output file and its ledger row may remain. A complete fix needs Store batch transactions,
same-volume staging, a commit/rollback journal, and crash recovery; it is outside Feature 085.

There is also an unavoidable evidence gap in the current command runner between successful
`Popen` and durable publication of `.execution.json.tmp`. A hard crash in that interval leaves no
durable fact that proves whether candidate code started or completed. Strict exactly-once execution
would need a durable pre-launch protocol or a separate transactional execution service.

These offline tests make no claim of effectiveness gain, effective-solution-rate gain, or parity
with WebAgent. A real framework integration, provider run, remote backend, or comparative campaign
requires a separately frozen feature and measurement record.
