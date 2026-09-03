# Research: Verified Algorithm Candidate Execution

## Current boundary

Native `loop` and `population` strategies already normalize candidate drafts, archive source files,
and validate `EvaluationReport`. `CommandCandidateEvaluator` currently receives only a candidate
path, so a model or evaluator process can produce a structurally valid report without proving that
the candidate ran. The new boundary must add evidence without changing the old callable protocol.

## Decision

Add a composable `CandidateRunner` in the evolution layer and an execution-aware evaluator adapter.
The runner receives a candidate path and writes one bounded, run-relative `execution.json` beside
the candidate. The evaluator command keeps its existing candidate-path argument and discovers the
evidence file through a documented stable location. A wrapper rather than a new evaluator protocol
preserves library and CLI compatibility.

The runner returns structured status and bounded output metadata. It never decides validity or score;
the independent evaluator remains authoritative. Runner errors are converted to a controlled invalid
report, preserving the existing validity-first invariant. Execution artifacts are indexed by the
controller like other runtime artifacts.

## Alternatives considered

1. **Let the model claim execution success** — rejected because this is the exact trust gap that
   prevents reliable algorithm effects.
2. **Replace the evaluator command protocol** — rejected because existing command evaluators and
   parent-Agent wrappers already depend on receiving one candidate path.
3. **Vendor a platform-specific sandbox** — rejected for the local-first standard-library base;
   process, timeout, output, and path guards are portable and composable with an optional sandbox.
4. **Make execution mandatory for every historical run** — rejected to preserve callback,
   command-only, Agent-backed, and OpenEvolve compatibility during migration.

## Harness implications

Codex `exec`, DeepSeek Harness headless/ACP, Claude Code CLI, Hermes, and OpenClaw can provide the
explicit runner process later. They remain execution-plane providers. Lunar-Agent retains ownership
of candidate identity, evidence paths, evaluator authority, archive selection, and durable resume.
