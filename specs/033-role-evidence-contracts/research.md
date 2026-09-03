# Research: strict role evidence contracts

## Decision 1 — Reuse declarative acceptance

The controller already evaluates bounded local files after the base evaluator and persists a
structured tree. Adding role-specific leaves keeps the security boundary in one interpreter and
avoids a second evaluator implementation.

## Decision 2 — Keep EvaluationReport as the authority

`EvaluationReport.from_dict` already enforces validity-first invariants used by loop, population,
and OpenEvolve bridges. The `evaluation_report_valid` leaf calls that model rather than defining a
second schema. This prevents a role report from claiming a positive score for an invalid candidate.

## Decision 3 — Record, do not promote, role files

Role artifacts are evidence for the next role and audit trail, not business outputs. They remain in
attempt workspaces and are copied through the existing dependency-artifact hand-off. Only the
Solver's declared `OutputSpec` files may be promoted to run-level `output/`.

## Decision 4 — Opt in through the specialist plan

The four-stage conversational plan and arbitrary custom plans retain their existing behavior. The
specialist role factory attaches these leaves explicitly, so a plan's immutable JSON is enough to
replay the same requirements after retry or resume.
