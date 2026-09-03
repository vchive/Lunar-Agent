# Implementation Plan: Contract-Driven Algorithm Playbooks

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

`AgentCandidateGenerator._prompt()` already joins the canonical contract, Feature 044 experiment
memory, and Feature 045 search directive. Feature 046 adds a pure projection at that same bridge.
No public request/configuration type, strategy, evaluator, archive record, or CLI option changes.

## Decisions

1. **Small native repertoire** — use five stable family tags per problem type. Every family must be
   implementable with Python's standard library so the prompt never promises an absent dependency.
2. **Allocate by measured attempts** — Feature 044 aggregates cards across the complete archive and
   pins the five relevant canonical family tags inside its bounded outcome summary. This avoids the
   display cap changing long-run allocation without scanning the archive twice. Explore/diversify
   choose untried then least-tried families.
3. **Lineage before global history** — repair and refine keep a target/parent family when declared;
   recombine projects distinct family tags from selected inspirations. This avoids changing the
   concrete structure and algorithm family in the same repair experiment.
4. **Verified success only as fallback** — if refinement has no recognized lineage family, prefer a
   repertoire tag with an `improved` outcome. Model metadata cannot provide that outcome.
5. **Checks, not generated code** — playbooks carry canonical trap/validation labels and contract
   constraint IDs, not executable snippets, raw data, output contents, or solver dependencies.
6. **Prompt-only compatibility** — legacy source responses remain legal. Agents are requested, but
   not trusted or required, to include the selected family tag in `experiment.change_tags`.

## Data flow

```text
canonical AlgorithmProblemContract -----------+
Feature 045 search_directive -----------------+--> algorithm_playbook --> solver prompt
Feature 044 full-archive verified tag counts --+
selected parent / repair target / inspirations+

solver {source, experiment.change_tags=[family_tag, ...]}
        -> execution -> independent evaluator -> archive-derived next allocation
```

## Repertoire policy

| Mode | Selection policy |
|---|---|
| explore | first untried canonical family |
| diversify | least-attempted family, preferring untried |
| repair | target's recognized family, otherwise repertoire default |
| refine | parent's recognized family, then verified-improved family, then repertoire default |
| recombine | parent's recognized family plus distinct inspiration families |

## Recovery and safety

- Exact tag matching prevents arbitrary model text from becoming playbook policy.
- Contract IDs and every playbook array are capped at eight; repertoire constants contain no
  executable content.
- Existing prompt compaction removes older cards/source excerpts while retaining the small
  directive and playbook.
- Missing/legacy experiments degrade to deterministic defaults.
- A fresh process recomputes everything from the request and append-only archive.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Standard-library algorithm families; no dependency. |
| Local-First and Durable State | Pass | Reconstructed from contract/archive. |
| Runtime Adapter Isolation | Pass | Only Agent prompt contents change. |
| Artifact-First Verification | Pass | Family attempts join independently evaluated cards. |
| Bounded Autonomy | Pass | Fixed repertoire/limits, no extra model turn. |
| Test-First Recovery | Pass | Domain/mode/population/restart tests precede code. |

## Complexity tracking

No CLI flag, database migration, persisted scheduler state, service, model call, dependency, or
evaluator change.
