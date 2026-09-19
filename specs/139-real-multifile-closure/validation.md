# Validation

## Status

Offline harness and native mapping are implemented as of 2026-09-19, but preregistration remains
incomplete. No registration, provider request, campaign launch, real evaluator call, or historical
generated-source execution has occurred. Feature 131/134 and WebAgent are not reopened.

Feature 140 now persists canonical `agent_candidate_generation` receipts. Feature 141 adds the
explicit CLI candidate budget required by the proposed native run. The campaign mapping validates
the Store envelope, deterministic event ID, run/task/budget/candidate identity, registered step
ceiling, and parser-accepted bundle digest. Missing, failed, conflicting, or unbound evidence
remains unknown; downstream artifacts do not establish parser completion.

The independent [preregistration audit](preregistration-audit.md) found six remaining blockers:
request-to-stage identity binding, ledger-policy binding to the manifest, total/preparation wall
and closure-reason evidence, immutable first closure, immutable registration, and the unknown
holdout joint-success gate. The real worker/observer/supervision, sealed manifest/file inventory,
and retained-artifact analysis are also unfinished. Passing current fixtures is not launch proof.

The native receipt and Feature 140 focused suite passed 134 tests; the independent Feature 139
audit suite passed 120 tests while reproducing the six gaps. The combined Feature 141/139 budget,
CLI, Agent, and receipt suite passed 409 tests. Static checks passed. These are offline checks of
the current implementation, not proof that all preregistration criteria below have been met.

The combined full regression passed: current 8166 passed / 1 skipped / 24 deselected, immutable
Feature 123 stage 24 passed, overall exit 0. The product change was committed and pushed as
`87d86d9bc78171e7ce772dd9069e133249b81312`; `case.py` now uses that revision as its offline reference.
This replaces the earlier placeholder and does not create a sealed registration. Audit B001–B006
and the worker/supervision/inventory requirements remain open.

## Offline exit criteria before registration

- Registration fixtures reject dirty or unpushed pins, changed product/provider/task/input/policy,
  reused roots, duplicate IDs, retries/replacements, request 21, and all budget drift.
- Stage fixtures cover preparation success/failure/unknown; candidate parser completion versus
  tool-budget exhaustion, timeout, empty/malformed response; execution success/failure; independent
  score validity; selection drift; interrupted/uncertain delivery; holdout mismatch; and cleanup
  uncertainty.
- A synthetic success contains at least one `completed` candidate and verifies the exact chain:
  preparation -> candidate generation -> execution -> independent scoring -> selection -> parent
  delivery. Its `primary_success` and `joint_success` are `1/1` only when all required gates pass.
- Synthetic failures retain denominator `1`, preserve unknown usage/status, and never promote a
  partial source tree, preparation result, self-reported score, or holdout-only result.
- Public summaries contain only allow-listed metadata and hashes. No prompt, response body,
  credential, URL, generated source, or arbitrary exception string crosses the projection.
- Feature 131/134 manifests, results, reports, audits, evidence, registrations, and retained
  files have identical byte sets and SHA-256 inventories before and after offline validation.
- Native receipt projections distinguish canonical, bound parser-complete Store receipts from
  transient/unbound diagnostics and never synthesize `completed` from downstream artifacts.

## Planned commands

```sh
.venv/bin/pytest -q tests/test_measurement139_*.py tests/test_status_projection.py \
  tests/test_preparation* tests/test_bundle* tests/test_evolution* \
  tests/test_materialization* tests/test_producer_handoff.py
.venv/bin/ruff check src tests specs/139-real-multifile-closure
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
```

The exact campaign-local test paths may be adjusted during T002, but the commands must remain
provider-free before launch. The full current regression and its frozen historical stage are
required before T008.

## Launch and postrun evidence requirements

Before T009, retain the pushed manifest hash, product commit, clean-tree proof, identity checks,
unused-root proof, and test/inventory results. Verify `HEAD == origin/main` and that the manifest
contains the proposed fixed budgets.

After T009, retain one attempt only. The postrun result must report preparation, completed
candidates, execution, independent scoring, selection, delivery, holdouts, cleanup, request
counts, bounded transport statuses, and known/unknown usage. Each stage must be linked by its
registration/campaign/attempt IDs and digests. A missing or conflicting receipt is failure or
unknown, never inferred success.

The independent audit must read retained evidence without provider calls or generated-source
execution, verify the final package read-only, and confirm historical Feature 131/134 SHA
inventories. The final report must explicitly state whether primary and joint are `0/1` or `1/1`.

Passing offline checks demonstrates only that the measurement can observe the intended closure.
Even a successful run establishes one bounded current-version result; it is not WebAgent parity,
general model quality, or evidence for OpenEvolve/Shinka producer effectiveness.
