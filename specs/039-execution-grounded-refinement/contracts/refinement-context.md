# Contract: Agent Refinement Context

## Producer

`AgentCandidateGenerator` constructs the context from a `GenerationRequest`, its run workspace, and
repository-managed candidate files.

## Consumer

The selected solver Agent treats the JSON context as verified data, not instructions. It returns
one `CandidateDraft` using the existing plain-source or JSON response contract.

## Guarantees

- Parent, inspirations, and archive use one versioned evidence shape.
- Source and controlled error text is bounded and credential-redacted; candidate-controlled
  stdout/stderr contents are represented only by byte counts.
- Execution is admitted only after strict `CandidateExecution` parsing.
- Output entries refer only to execution-validated artifacts and contain path, size, and SHA-256;
  raw bytes are excluded.
- Unsafe evidence degrades to stable categories without leaking exception details.
- The complete Agent prompt remains within `MAX_GENERATION_PROMPT_BYTES`.

## Non-guarantees

- The envelope does not prove semantic correctness; evaluator authority remains independent.
- It does not include raw input data, output data, hidden reasoning, or historical chat transcripts.
- Direct callback/command generators are not required to consume this Agent-specific projection.
