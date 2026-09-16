# Plan

Add SourceCheckSpec beside ConstraintSpec and a pure source_constraints module for declaration selection,
deterministic evidence and report construction. Reuse CandidateSourceBundle validation and hashes.
Root owns schema, prompts, evaluator probe coverage and automatic preparation scope compatibility.

Candidate evaluation verifies original source bytes as before, computes source evidence before
scoring and retains that evidence outside the harness-visible files until the harness finishes.
Source-aware record protocol adds source_constraints_valid; one source-checks.json contains the
full bound bundle and results. Read-only inspection requires canonical evidence and recomputes it.
Old records use the exact previous shape/protocol when no supported source check exists.

Delivery carries evaluation/source-checks.json and validates it against its contract, source bundle,
and actual delivered source bytes. Existing authority and selected-candidate digest checks remain.
Do not expand evaluator visibility to source or ask generated probes to validate file structure.

Alternative rejected: filtering all partial constraints, trusting model-claimed file count, running
source imports, or applying a static import heuristic as proof of standard-library-only execution.
No dependencies, migration, or constitution exceptions. Legacy absent-field identities stay stable;
new requirements are hashed into the contract and cannot be grafted onto frozen old results.

Run focused parser/probe/evaluation/delivery/CLI tests, the existing 112 quickstart, a new source-aware
local scenario and full regression after implementation freeze. Commit/push verified changes.
