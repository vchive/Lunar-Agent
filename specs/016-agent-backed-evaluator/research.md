# Research Notes: Agent-Backed Evaluator

## Existing seams

`CandidateEvaluator` already returns an `EvaluationReport` and the archive validates it before
selection. Feature 014's Agent Adapter provides bounded JSON/text invocation; Feature 015's
`AgentCandidateGenerator` demonstrates how to construct bounded algorithm context.

## Decisions

1. Add `AgentCandidateEvaluator` next to the generator bridge, keeping evolution strategies and the
   evaluator contract runtime-neutral.
2. Pass the candidate path rather than copying full source into the prompt. The worker runs in the
   candidate's run-relative parent and can inspect the source locally.
3. Require strict JSON for evaluation (no plain-text fallback), then call `EvaluationReport.from_dict`
   to enforce validity-first score and error invariants.
4. Make the evaluator Agent CLI option mutually exclusive with the existing evaluator command.

## Rejected alternatives

- Parsing a natural-language score: ambiguous, unverifiable, and incompatible with the structured
  evaluator contract.
- Letting the solver Agent evaluate itself: risks correlated errors; callers should register
  distinct solver/evaluator adapters when independence matters.
