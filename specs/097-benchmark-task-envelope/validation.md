# Validation — 2026-09-14

## Results

- Failure-first test collection reproduced the missing `famou.benchmark_task` module before implementation.
- Benchmark and task-envelope focused tests: **19 passed**.
- Ruff and compileall passed for the new module, CLI, exports and tests.
- Full regression before final pin-symmetry/private-path refinements: **3842 passed in 210.24s**.
  Final focused benchmark/CLI regression after those refinements: **79 passed in 7.97s**.
- No real SkyDiscover, LLM4AD, model, provider, external framework, remote service or campaign was run.
- Feature 051/074/076/078/082 sealed files remain outside this change.

## Behaviors exercised

- Strict schema/protocol parsing, canonical round-trip and stable envelope/comparison digests.
- Equivalent SkyDiscover and LLM4AD fixture mappings share comparison identity while framework names
  and release labels remain outside the workload comparison digest.
- Unknown fields, duplicate JSON keys, nonfinite values, unsafe/private paths, secret-like text,
  invalid candidate kind and out-of-range budgets are rejected with fixed error codes.
- Admission rechecks contract, model, evaluator and optional budget pins, then verifies confined
  input regular-file size and SHA-256 without writing or executing anything.
- Changed, missing, linked and escaped input files fail closed. The CLI validates before normal
  configuration initialization and returns only task identity, counts and digests.

## Scope and retained limits

The envelope contains digest-only inputs and no external framework score or generation authority.
It supports a bounded single-file candidate task. Repository/workflow candidates, training/RL
artifacts, remote lifecycle and actual benchmark comparison require later contracts and fixed
pre-registered measurements.
