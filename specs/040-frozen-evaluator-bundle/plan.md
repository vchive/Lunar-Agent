# Implementation Plan: Frozen Evaluator Bundle

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

The conversational compiler already creates an immutable `AlgorithmProblemContract`; Feature 037
guarantees each native candidate is executed and output-validated before the candidate evaluator.
The new bundle compiler consumes the same explicit repository runtime once, produces a local
`CandidateEvaluator`, and plugs into `ExecutionAwareCandidateEvaluator`. No strategy API changes.

## Decisions

1. **Explicit first release** — `--compile-evaluator` opts into generated executable authority;
   ordinary model evaluation and user commands remain available.
2. **Strict JSON protocol** — generated prose cannot become an evaluator. The envelope is bounded,
   rejects unknown fields, and carries declarative probes rather than executable test code.
3. **Repository-owned preflight** — Lunar-Agent builds probe workspaces, runs the evaluator, parses
   reports, checks constraint codes, and verifies score ordering.
4. **Freeze by content** — manifest hashes bind contract, objective, evaluator, and probes. Files
   become read-only; strategy resume binds the aggregate digest.
5. **No solver access** — the bundle lives below the intake workspace, not candidate generation
   workspaces. Solvers receive only bounded evaluation/refinement reports.
6. **Fail before archive mutation** — bundle compilation and preflight complete before creating or
   resuming candidate search state.

## Data flow

```text
contract + output schemas
          |
          v
 evaluator compiler runtime (once)
          |
 strict bundle envelope
          |
 static checks -> validity probes -> score-order probes
          |
 hash + read-only freeze + artifact index
          |
          v
ExecutionAwareCandidateEvaluator -> native loop/population archive
```

## Recovery and safety

- Bundle creation uses a private staging directory and atomic directory promotion.
- Probe paths are portable and confined; contents, counts, and aggregate bytes are bounded.
- Evaluator processes use isolated Python and minimal deterministic environment.
- Loader rejects symlinks, unexpected files, permission drift, digest drift, contract drift, and
  malformed manifests.
- Generated source is not a complete OS sandbox; local process authority is documented explicitly.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses repository runtime and stdlib subprocesses only. |
| Local-First and Durable State | Pass | Bundle is content-addressed below the intake run. |
| Runtime Adapter Isolation | Pass | Runtime compiles once; strategy consumes CandidateEvaluator. |
| Artifact-First Verification | Pass | Synthetic probes and real candidate files are parsed locally. |
| Bounded Autonomy | Pass | Explicit flag, AST restrictions, probes, timeout, minimal environment. |
| Test-First Recovery | Pass | Compile/preflight/freeze/resume failures precede implementation. |

## Complexity tracking

One repository module and one CLI flag are added. No dependency, database migration, service,
network protocol, or change to `GenerationRequest`/evolution strategy interfaces is required.
