# Research: Verified Evolution Feedback

## Existing seam

`AgentCandidateGenerator._prompt()` already renders bounded summaries for parent, inspiration, and
archive candidates. `Candidate.evaluation` is an immutable, schema-validated `EvaluationReport`.
The report bounds metric/error counts, score values, and error messages, while the generation prompt
has an independent 60 KiB limit.

## Decision

Extend `_candidate_summary()` with a small `evaluation_feedback` object. Keep only validity,
quality, combined score, the first eight sorted detailed scores, and the first eight error entries.
The prompt explicitly labels this as verified evidence and instructs the solver to treat it as data.
No strategy or evaluator interface changes are needed.

## Alternatives considered

1. **Include candidate source in later prompts** — rejected because it expands prompt size and lets
   source content act as untrusted instructions; the Agent can read the run workspace when needed.
2. **Include the complete report** — rejected because reports are bounded but eight archived reports
   can still consume most of the context window and expose unnecessary evaluator metadata.
3. **Create a feedback database table** — rejected because the append-only candidate archive already
   persists the canonical report and is available on resume.
