# Plan: Corrected Staged Workflow Measurement

## Decisions and alternatives

Use one fresh1200-second staged attempt per case. The prior300-second arms both timed out;
repeating them would not answer the current corrected-handoff question. Do not mix a role/prompt
change or another normal arm into this registration. Older samples are context, not controls.
Reuse immutable069/072 helpers through an explicit private loader with pinned bytes and isolated
globals. Replace only hardcoded two-slot registration/verification/aggregation orchestration;
never alter an old manifest or manufacture extra slots to satisfy a four-slot checker.

## Data model and contracts

Keep existing native request, workflow, receipt, outcome and record schemas. The new manifest has
planned_attempts=2, slots1/2 with arm=S/budget_arm=master_1200, policies with that single budget,
and waves=[[1,2]]. Each workflow binds its own run/attempt/request/source/profile/case/ceilings.
The summary contains two rows and one budget group with a fixed denominator2; precise Master
duration stays null. New scripts and all actually loaded historical helpers/tests are frozen.
The preaudit independently checks Git source, public/private case and harness bytes, exact
dependencies and the fixed schedule. Postrun reads native records and the pinned072 read-only
workflow validators without invoking recovery constructors or dispatching.

## Ordered work and quickstart

1. Specify protocol; implement minimal prepare/audit/worker/campaign and offline tests.
2. Reuse pinned postrun phase validation; add two-slot completion/registration/reporting.
3. Run targeted/offline checks and independent cross-review, then materialize once and audit/dry-run
   the exact registration. Commit/push all executable sources, registration and reports.
4. Launch once, observe both attempts without changing frozen bytes, finish final audit/process
   checks and seal results. Do not turn a failed attempt into a retry after looking at outcomes.

```sh
.venv/bin/python -B -m pytest -o addopts='' -q tests/test_measurement074*.py
.venv/bin/python -B specs/074-corrected-staged-measurement/measurement/prepare.py
.venv/bin/python -B specs/074-corrected-staged-measurement/measurement/campaign.py --check-only
.venv/bin/python -B specs/074-corrected-staged-measurement/measurement/campaign.py --dry-run
# Save mirrored reports, independently review, commit/push, then exactly once:
.venv/bin/python -B specs/074-corrected-staged-measurement/measurement/campaign.py --launch
# Observation only after launch:
.venv/bin/python -B specs/074-corrected-staged-measurement/measurement/campaign.py --summarize
.venv/bin/python -B specs/074-corrected-staged-measurement/postrun/audit.py
```

## Constitution and migration

No exception or product migration. A bounded local measurement uses the existing runtime adapter,
durable native state and independent artifact verification. No new dependency or score authority.
Provider variability, one-sample-per-case limits, public projection not being an OS sandbox and
unavailable precise Master timing remain explicit limitations.
