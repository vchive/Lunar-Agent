# Feature 144 validation

## Scope and findings

This feature follows the frozen Feature 139 audit without replaying or modifying that attempt.
The multi-file generation prompt described experiment arrays ambiguously, while the general
AgentLoop system prompt requested a final summary. Both are now addressed with an explicit
invocation-local bundle protocol and parser-valid response examples. This is a concrete prompt
conflict repair, not proof that either issue was the sole cause of the historical failure.

The receipt boundary also rejected the runtime's existing `timeout`, `tool_failed` and
`empty_response` aliases, and discarded observed failure phase. Their safe canonical projection
now retains optional phase and typed model failure cause for failures, with no private text.
Parser rejection retains valid runtime counts. Runtime diagnostics are bound to the current
invocation; runtime completion alone is not parser acceptance.

## Verification

The final quickstart runs all three new suites: **100 passed in 0.81s**. These include 37 protocol
cases, 43 failure-diagnostic cases and 20 actual generator/AgentLoop/Store integration cases.
The latter execute and independently score valid synthetic bundles, and verify that malformed
responses, typed model failures and rejected tool batches never reach downstream execution.

The shared suite (the three new files plus agents, AgentLoop, evolution, bundle generation,
command adapter, durable receipt and Feature 139 native receipt regressions) passed:
**297 passed in 3.21s**. Reports are in `.lunar/test-results/feature144/shared.xml` and
`quickstart.xml`. The full split runner also passed: **8848 passed, 1 skipped, 24 deselected**
in 1441.77 seconds for the current suite, then **24 passed** in 27.08 seconds for frozen123.
Both phases and the overall runner returned exit 0. Reports and the runner's import/pin record
are in `.lunar/test-results/feature144/full/`; the log is `feature144/full-run.log`.

Ruff for `src tests tools`, compileall for `src tests`, Specify prerequisites and diff checks pass.
Two independent reviews passed after fixing duplicate base-AgentError emission and removing
external runtime self-reported model causes. Stale getter copies, current emitted observations,
ordinary/bundle/ordinary reuse, custom system constraints and transcript isolation are covered.

One final defensive change uses `getattr` for a malformed typed evidence object whose reason
field is missing. It was made after the full run started; the final 100-case quickstart above
ran after that change. The earlier shared count is not relabeled as a rerun of those final bytes.
The final product commit `c6947fdfbf43d84e83cc29cc215e7bc0250db83a` passed the complete
[Linux CI matrix](https://github.com/vchive/Lunar-Evolution/actions/runs/35556293182), confirmed at
2026-09-21 03:28:01 UTC. Python 3.11, 3.12 and 3.13 each passed installation, complete split
regression, failure annotations, result preservation and Ruff. This validates the final product
bytes including the defensive change above. The follow-up recording commit is documentation only.

Read-only inventory checks before and after implementation matched every path, size and SHA-256 in the existing
Feature 131/134/139 evidence inventories: 21 / 97 / 70 files and
155485 / 327394 / 298462 bytes respectively.

## Evidence limits

No provider request or new campaign is part of this feature. Scripted-model integration may
execute new, local synthetic candidate/evaluator fixtures; it never replays historical generated
source. Existing bundle parsing, independent evaluation, success identity and tool limits remain
authoritative. Historical Feature 139 remains preparation 1/1, primary/joint 0/1.

Real model completion improvement and complete parent delivery still require a new, independently
registered acceptance run. Automatic background execution (142 Phase C) and worker consumer
integration (143 T009) remain incomplete.
