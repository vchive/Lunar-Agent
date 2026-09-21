# Validation

## Status

Implementation and offline validation completed on 2026-09-19. No provider request, real campaign evaluator invocation, provider-generated-source
execution, Feature 139 registration, or historical campaign resume is part of this SDD. Local
repository-owned synthetic candidate and evaluator fixtures may execute to verify the product path.

## Completed independent checks

- CLI static validation: Ruff, Python bytecode compilation, and `git diff --check` pass.
- Specify prerequisites pass with `--require-tasks --include-tasks` for this feature directory.
- The initial local Markdown link check passed (1 link).
- Feature 131 retained evidence matches its postrun inventory exactly: 21 files, 155485 bytes,
  with identical relative file set, byte sizes, and SHA-256 digests.
- Feature 134 retained evidence matches its postrun inventory exactly: 97 files, 327394 bytes,
  with identical relative file set, byte sizes, and SHA-256 digests.

## Profile compatibility finding and resolution

The focused propagation review found an existing interaction between Feature 136's explicit
profile ceiling and Feature 140's durable receipt arithmetic. With candidate authority 12 and
`ModelProfile.max_steps=2`, a parser-accepted zero-tool candidate produces an effective runtime
diagnostic with 2 remaining steps. The generator combines that value with authority maximum 12,
so receipt validation rejected `0 + 2 != 12` as `invalid_tool_budget`.

The generator now validates the effective runtime count tuple before projecting receipt remaining
against candidate authority. With authority 12 and profile ceiling 2, runtime diagnostics remain
at effective maximum 2; successful zero-, one-, and two-tool candidates retain authority 12 and
receipt remaining 12, 11, and 10 respectively. A returned three-tool batch is still atomically
rejected before any write, final response, or completed candidate identity. Incomplete, malformed,
inconsistent, and over-authority runtime tuples fail instead of becoming valid receipt evidence.
The receipt schema, exact arithmetic check, runtime limit, and failure diagnostic semantics are
unchanged.

The narrow generator/receipt/adapter suite passed: 81 tests across `test_agent_evolution.py`,
`test_candidate_generation_receipt.py`, and `test_agents.py`; Ruff, bytecode compilation, and
diff checks passed. An independent zero-tool reproduction also confirmed effective maximum 2 and
completed receipt `(maximum=12, used=0, remaining=12)`.

## Final verification results

- Combined CLI/preparation/generator/Agent-loop/receipt and Feature 139 suite: **409 passed in
  29.88s**. This includes 88 automatic multi-file CLI tests.
- Full current regression: **8166 passed, 1 skipped, 24 deselected in 612.97s**.
- Frozen Feature 123 stage: **24 passed in 15.82s**. Its original 77 product, 14 measurement,
  and 69 historical file pins were verified by the split runner; overall exit status was 0.
- The full run included the concurrent Feature 139 offline harness/native mapping changes. Those
  tests passing does not close its separately documented preregistration audit gaps.
- Ruff over `src`, `tests`, and both feature directories; compileall; diff and local link checks
  passed. Independent review found no remaining blocker for Feature 141.
- Feature 131/134 retained inventories were checked again after the regression and stayed exact.
- Local JUnit reports are `.lunar/test-results/feature141/current.xml` and `frozen123.xml`.

## Verified focused acceptance matrix

- Parser fixtures accept integer candidate-step values from 1 through the repository maximum and
  reject zero, negative, boolean, non-integer, non-finite, and out-of-range values before creating
  a Store, run, runtime, preparation attempt, child workspace, or provider request.
- Mode fixtures reject the option without native automatic `solve --evolve --multi-file`, with
  explicit bundle profiles, evaluator/producer commands, non-population strategies, standalone
  `evolve-bundle`, and ordinary non-evolution solve.
- A fresh automatic request with `--candidate-generation-max-steps 12` persists only bounded
  policy metadata, including value and explicit source; omitted requests retain no field and no
  implicit budget. Paths, prompts, secrets, and model text are absent.
- `resume` and `answer` restore the stored value when omitted or repeated exactly. A changed value
  and a value added to a legacy handoff fail before preparation, child creation, provider request,
  or candidate execution; Store state and prior events remain unchanged.
- Fresh and resumed automatic bundle generator fixtures observe an immutable
  `CandidateGenerationBudget` with the requested step ceiling, base identity, and resolved
  request timeout. The resulting `AgentRequest` carries the per-request identity and Feature 140
  can persist a matching receipt when the generation reaches its existing parser boundary.
- Runtime loop defaults and explicit profile ceilings remain independent. A profile may narrow the
  effective runtime ceiling under Feature 136, but a model response or runtime default cannot
  enlarge the candidate authority. Whole-batch overrun remains atomic with no retry or prefix.
- Standalone `evolve-bundle`, explicit profiles, single-file evolution, deterministic/command
  generators, and producer seed paths retain their existing request and state shapes.
- Feature 139 tests remain provider-free; this product feature does not modify their measurement
  contract. Feature 131/134 retained files and their byte/SHA inventories are identical before
  and after implementation.

## Verification commands

```sh
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_conversational_automatic_bundle.py \
  tests/test_preparation_budget_status.py tests/test_preparation_wall_timeout_cli.py \
  tests/test_agent_evolution.py tests/test_agents.py \
  tests/test_agent_loop.py tests/test_candidate_generation_receipt.py \
  tests/test_measurement139_*.py
.venv/bin/ruff check src/lunar_evolution/cli.py src/lunar_evolution/agents.py \
  src/lunar_evolution/agent_evolution.py tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY=specs/141-native-multifile-cli-budget \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature141
```

The exact focused test list may be narrowed after implementation, but every check must remain
offline. The full current regression and frozen historical stage are required before a product
commit. A green suite proves CLI authority propagation only; it does not establish model
completion, provider usage, quality, or WebAgent parity.

## Launch boundary after completion

Feature 141 completion permits Feature 139 to prepare a fresh manifest that explicitly passes
`--candidate-generation-max-steps 12` and uses its registered ordinary timeout. It does not itself
authorize a provider request. Feature 139 must still pass its own preregistration, push, unique
slot, historical inventory, and campaign audit gates.
