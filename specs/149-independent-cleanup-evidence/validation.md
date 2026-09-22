# Validation

Feature 149 is implemented as a provider-free offline slice. The focused cleanup, native execution
evidence, runner, acceptance-audit, and slot selections pass **291 tests**. The exact selection is:

```sh
.venv/bin/python -m pytest -o addopts= -q --disable-warnings \
  tests/test_candidate_execution_cleanup.py \
  tests/test_candidate_execution_evidence.py \
  tests/test_candidate_execution_evidence_files.py \
  tests/test_candidate_execution_files.py \
  tests/test_candidate_execution_runner.py \
  tests/test_candidate_execution_runner_files.py \
  tests/test_acceptance_audit.py \
  tests/test_acceptance_audit_native.py \
  tests/test_audit_slots.py
```

The suite uses the repository's bounded local fixture process to verify publication and callback
ordering; it does not call a provider, evaluator, campaign, or historical generated source.

Coverage includes canonical round trips, prior-record binding, malformed and noncanonical JSON,
digest tampering, missing or mismatched observer/release identities, live/unknown group probes,
callback failure, failed/unknown cleanup, completion descriptor binding,
copied/inode-replaced cleanup, old three-file v1 records remaining unknown, and the rule that
later evidence cannot promote a missing cleanup receipt. The native inspector exposes only
cleanup status and digest; PID/PGID remain private receipt fields.

The runner's process result schema is unchanged. A new attempt writes `cleanup.json` only after
the process boundary returns and binds its descriptor from `completed.json`; a legacy attempt
without that file remains `execution_cleanup_unknown`. The acceptance auditor promotes the
execution boundary only for a verified cleanup receipt, while failed or malformed receipts leave
primary and joint eligibility closed. No historical evidence is migrated or rewritten.

Ruff, compileall, diff checks, and the complete three-stage regression pass: current product
**7238 passed, 1 skipped**, fixed archive **2294 passed**, and frozen registration **24 passed**,
with overall exit 0. Commit `806b97f` is pushed and GitHub Actions [Run 230](https://github.com/vchive/Lunar-Evolution/actions/runs/35749740921)
passed on Python 3.11, 3.12 and 3.13. No provider or real campaign launch is part of this
feature.
