# Feature Specification: Contract-Driven Algorithm Playbooks

**Feature Branch**: `046-contract-driven-algorithm-playbooks`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Feature 045 tells an Agent solver whether a generation should explore, diversify, repair, refine,
or recombine. The solver still receives one generic Python instruction for every problem type. It
must rediscover elementary routing, scheduling, packing, assignment, network-flow, continuous, and
forecasting algorithm families on every fresh turn. Population seeds can therefore be textually
different while remaining algorithmically identical.

WebAgent v2.5 improves this with large OR/ML specialist prompts and skills. Lunar-Agent needs the
quality effect, but not an OpenCode installation, mutable skill directory, third-party solver
assumption, or service plane. This feature projects a small repository-owned `algorithm_playbook`
from the canonical problem contract, selected search mode, lineage, and verified experiment
memory. The playbook recommends a stable standard-library-capable algorithm family and explicit
modeling/validation checks. It guides the existing solver turn only; generated code still executes
and is independently evaluated through the existing authority boundary.

## User stories and acceptance scenarios

### User Story 1 — Start from a domain-appropriate algorithm family (P1)

1. Each supported `problem_type` receives a bounded domain playbook with a deterministic first
   family, alternatives, modeling checks, and validation checks.
2. Playbooks recommend techniques implementable in a self-contained Python candidate without
   requiring globally installed solvers or Agent frameworks.
3. Canonical hard-constraint IDs and objective direction are included as data, while arbitrary
   constraint prose and raw input values are not duplicated.

### User Story 2 — Allocate real algorithmic diversity (P1)

1. `explore` selects the first untried family and parentless `diversify` selects the least-attempted
   untried family based on archive-derived experiment tags.
2. A population Agent that reports the requested family tag receives different seed families until
   the repertoire is covered rather than repeated generic sampling.
3. When all families have been attempted, selection is deterministic by attempt count and canonical
   order; a model cannot claim an outcome to alter that count.

### User Story 3 — Preserve useful structure during repair/refinement (P1)

1. `repair` keeps the target candidate's declared canonical family when available and prioritizes
   feasibility checks.
2. `refine` keeps the selected parent's canonical family; absent lineage evidence it prefers a
   canonically recognized family with evaluator-verified improvements.
3. `recombine` names the parent's family and distinct inspiration families, allowing the solver to
   combine structures without treating an invalid candidate as quality evidence.
4. A fresh generator reconstructs the same playbook after restart without a database migration,
   skill installation, or extra inference call.

## Functional requirements

- **FR-4601**: Add one versioned prompt-only `algorithm_playbook` with problem type, search mode,
  objective direction, selected family tag, alternatives, selection basis, hard-constraint IDs,
  modeling checks, validation checks, and a non-executable instruction.
- **FR-4602**: Define a repository-owned ordered repertoire for every currently supported problem
  type using safe stable family tags and standard-library-capable methods.
- **FR-4603**: Derive explore/diversify allocation from exact canonical family tags using Feature
  044 card semantics over the complete archive; count evaluator-derived cards of every outcome and
  select untried/least-tried families deterministically, independent of bounded prompt summaries.
- **FR-4604**: For repair/refine/recombine, project canonical family identity only from normalized
  candidate experiment plans and pair it with Feature 045's verified mode/evidence selection.
- **FR-4605**: Bound each playbook array to eight strings, exclude raw rows/output contents and
  constraint descriptions, and preserve the existing 60 KiB generation prompt limit.
- **FR-4606**: Tell structured solvers to include the exact selected family tag in their experiment
  change tags so later allocation can measure attempts; continue accepting legacy/plain source.
- **FR-4607**: Keep strategy selection, candidate ranking, evaluator authority, archive format,
  command/callback generators, OpenEvolve, compiled scoring, and base dependencies unchanged.

## Success criteria

- **SC-4601**: Tests cover exact first-family and safety-check projections for all seven supported
  problem types.
- **SC-4602**: A deterministic population fixture receives distinct first and second seed families.
- **SC-4603**: Repair/refine/recombine tests retain target/parent/inspiration family evidence and
  never use model-claimed outcomes.
- **SC-4604**: Least-attempted selection, array bounds, prompt compaction, and fresh-generator
  reconstruction are deterministic.
- **SC-4605**: Focused/full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Installing OR-Tools, HiGHS, pandas, scikit-learn, or a domain skill marketplace.
- A model-selected router, learned portfolio/bandit, automatic hyperparameter tuning, or an extra
  critic/planner/reflection call.
- Claiming a playbook family is best without equal-budget benchmark evidence.
- WebAgent's HTTP/SSE, billing, cloud workspace, multi-tenant, or OpenCode process machinery.
