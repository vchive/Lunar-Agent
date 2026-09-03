# Implementation Plan: Execution-Grounded Conversational Evolution

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

`CommandCandidateRunner` already provides bounded process evidence and the pre-feature
`ExecutionAwareCandidateEvaluator` enforced runner failure only after calling the evaluator.
Feature 036 contains the proven Python/output protocol, while
`LocalController.copy_staged_inputs` supplies child-run input ledger integrity. The implementation
extracts a reusable contract-aware runner into the evolution layer and composes it only in the
native conversational handoff.

## Decisions

1. **Execution before model cost** — the wrapper returns a local validity-zero report immediately
   when process/output checks fail. Downstream evaluator calls are reserved for executable
   candidates.
2. **Search and delivery remain separate** — candidate directories retain search evidence, but the
   winner is re-executed in Feature 036's deterministic final workspace before parent promotion.
3. **Verified input descriptor** — the runner receives bounded `CandidateInputArtifact` records
   from the child ledger. It rechecks source bytes on every copy and never trusts a path alone.
4. **Existing output DSL** — exact `OutputSpec` rules use `acceptance_evaluator`; no competing schema
   parser or candidate-controlled manifest becomes authority.
5. **Evidence-grounded prompts** — candidate source is included up to a fixed byte cap. Execution
   JSON and output metadata are normalized into JSON. Raw input/output bytes stay local; tool-loop
   and explicit local runtime profiles can inspect staged copies when authorized.
6. **Native conversational scope** — loop/population get the automatic runner. Direct `evolve`
   preserves its explicit runner CLI and OpenEvolve remains responsible for its own internal search.

## Data flow

```text
verified child input ledger
        | digest-checked copy
        v
candidate archive directory
  candidate.py + data/raw/*
        | python -I
        v
execution.json + attempt output/*
        | OutputSpec validation
        +-- fail --> local validity=0; skip Agent evaluator
        |
        `-- pass --> source excerpt + execution/output metadata
                         | independent Agent evaluator
                         v
                    archive score/selection
                         |
                         v
                 clean-room final materialization
```

## Safety and recovery

- Input/output/candidate paths reject traversal and all symlink components, including dangling
  links. Size and digest are checked before and after atomic copy.
- Candidate processes receive no inherited model credentials. Stdout/stderr remain bounded in
  `execution.json`; evaluator prompts receive only normalized metadata.
- The runner fingerprint excludes absolute commands and credentials while binding the contract,
  input digests, protocol version, and interpreter version.
- Existing candidate directories with different staged input bytes fail instead of being changed.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses repository Python and standard library only. |
| Local-First and Durable State | Pass | Per-candidate evidence remains in the child archive. |
| Runtime Adapter Isolation | Pass | The runner/evaluator protocols remain injected composition. |
| Artifact-First Verification | Pass | Execution/output checks precede model scoring. |
| Bounded Autonomy | Pass | Paths, bytes, time, environment, and prompt evidence are bounded. |
| Test-First Recovery | Pass | Failure, tampering, resume, and legacy paths receive tests. |

## Complexity tracking

No service, dependency, or database migration is added. Source excerpts improve one-shot grounding
without pretending that a generic LLM score is a mathematical oracle; exact objective harnesses
remain explicit domain adapters and a later benchmark concern.
