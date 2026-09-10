# Plan: Public Plan Handoff Measurement

## Decisions and alternatives

Measure075 with the same two cases and1200-second Master configuration as074. Increasing the
planning allowance or changing role prompts now would introduce another configuration change.
The sheet timeout remains unresolved and must not be described as repaired. Use existing sealed
campaigns as context, never as concurrent controls or replacement attempts.

## Architecture and contracts

Keep native request/workflow/receipt/state/report schemas and exact harness. Small new wrappers
bind pinned074 two-slot helpers and their072/069 dependencies to the new identity, source and
history. Do not alias global sys.modules or mutate old files/manifests. Freeze the actual imported
closure and all new scripts/tests/inputs. No dummy slots or legacy four-slot entry points.
New preaudit checks source against Git, actual public/private case and harness, installed versions,
history, exact two-slot schedule, unstarted state and executable closure. Read-only postrun checks
registration commit, frozen bytes, native chain and workflow state without recovery construction.

## Ordered work and quickstart

1. Define protocol; implement minimal wrappers and focused new identity/binding tests.
2. Independently review and run deterministic guarded native fixtures, including075 vocabulary.
3. Materialize once, independently audit/dry-run actual inputs, mirror reports, commit and push.
4. Launch once, observe both slots without altering frozen bytes, independently audit final evidence
   and scoped process termination, seal reports and update HANDOFF.

```sh
.venv/bin/python -B -m pytest -o addopts='' -q tests/test_measurement076*.py
.venv/bin/python -B specs/076-public-plan-handoff-measurement/measurement/prepare.py
.venv/bin/python -B specs/076-public-plan-handoff-measurement/measurement/campaign.py --check-only
.venv/bin/python -B specs/076-public-plan-handoff-measurement/measurement/campaign.py --dry-run
# Commit/push registration and mirrored readiness reports before exactly one launch:
.venv/bin/python -B specs/076-public-plan-handoff-measurement/measurement/campaign.py --launch
# After launch use observation only:
.venv/bin/python -B specs/076-public-plan-handoff-measurement/measurement/campaign.py --summarize
.venv/bin/python -B specs/076-public-plan-handoff-measurement/postrun/audit.py
```

## Constitution and migration

No exception, runtime migration or new dependency. Native local state, bounded resources and
independent artifact verification remain the authority. Observation can race with a live write
and must reject/re-read rather than repair it. Final version/process checks are scoped snapshots,
not continuous tracking. Detailed limitations belong in the final report.
