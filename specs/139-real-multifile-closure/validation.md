# Validation

## Status

Specification-first as of 2026-09-19. No registration, provider request, campaign launch,
evaluator call, or generated-source execution has occurred. The files in this directory define the
next real acceptance only; they do not authorize reopening Feature 131/134 or comparing WebAgent.

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
