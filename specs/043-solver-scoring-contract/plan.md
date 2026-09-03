# Implementation Plan: Solver Scoring Contract

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

`AgentCandidateGenerator._prompt` reconstructs a compact contract from the child run's immutable
`evolution/contract.json`, while Feature 042 leaves a verified v2 evaluator bundle in the parent
intake workspace. Feature 043 adds one immutable value object between those boundaries and passes it
only to repository Agent generators used by the conversational compiled-evaluator path.

## Decisions

1. **Complete canonical constraints** — retain hard/soft constraints and assumptions when compacting
   persisted contracts; these are bounded by `AlgorithmProblemContract` already.
2. **Verified source only** — `FrozenEvaluatorBundle` re-runs loader verification before producing
   any solver-scoring object. A path alone is never accepted as scoring authority.
3. **Exact local files plus bounded prompt** — tool-capable Agents receive full objective/evaluator
   files in their isolated workspace; all Agents receive objective text and a source excerpt within
   the existing total prompt limit.
4. **Probes stay private** — neither compiler self tests nor adversarial attacks are useful solving
   inputs. Withholding them avoids teaching a candidate the exact admission test cases.
5. **Immutable copy, external authority** — staged scoring files are read-only guidance copies. The
   actual evaluator remains in the parent bundle and is reverified before every score.
6. **No new flag** — this is the semantics of the existing explicit `--compile-evaluator` mode.
   Other evaluators and generators are unchanged.

## Data flow

```text
verified v2 bundle ----> bounded SolverScoringContract
       |                          |
       |                          +-> generation/scoring/{objective,evaluator,manifest}
       |                          +-> prompt summary (objective + source excerpt + hashes)
       |
       +-------------------------------------------------> authoritative evaluation

canonical contract -> full hard/soft constraints ----------------------^ solver candidate
compiler probes + audit probes + private profile ----------------------X withheld
```

## Recovery and safety

- Bundle loader and handle fingerprint checks run before reading guidance bytes.
- Objective/source limits and the existing 60 KiB generation-prompt cap bound model context.
- Scoring paths are fixed repository names; staging rejects symlinks or conflicting existing bytes.
- The manifest contains digests and relative paths only, never parent workspace paths.
- Resume reuses frozen bytes and recomputes copies; no additional durable database state is needed.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses repository types and filesystem only. |
| Local-First and Durable State | Pass | Projection derives from the durable frozen bundle. |
| Runtime Adapter Isolation | Pass | Agent adapters receive the existing prompt/workspace contract. |
| Artifact-First Verification | Pass | Visible scoring code remains advisory; evaluator execution decides. |
| Bounded Autonomy | Pass | Fixed paths, read-only copies, hashes, prompt/source bounds. |
| Test-First Recovery | Pass | Constraint, privacy, tamper, integration, and resume tests precede code. |

## Complexity tracking

No service, database migration, dependency, CLI option, strategy state, or evaluator protocol
change. The new value object is active only for native Agent generation with a verified compiled
evaluator.
