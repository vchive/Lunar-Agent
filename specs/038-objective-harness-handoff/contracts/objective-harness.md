# Objective Harness Contract

Lunar-Agent invokes the explicit executable without a shell as:

```text
COMMAND... ABSOLUTE_CANDIDATE_PATH
```

The working directory is the candidate archive directory. Before invocation, Feature 037 has
verified `candidate.py`, `execution.json`, copied `data/raw/*`, and declared `output/*`. Stdin is
closed. The conversational handoff supplies only deterministic UTF-8/locale environment entries.

Stdout must contain exactly one bounded `EvaluationReport` JSON object. Non-zero exit, timeout,
oversized output, malformed JSON, or invalid schema is a candidate evaluation failure. Archive
selection maximizes the non-negative `combined_score`; the harness is responsible for objective
normalization and can retain raw directional values in `detailed_scores`.
