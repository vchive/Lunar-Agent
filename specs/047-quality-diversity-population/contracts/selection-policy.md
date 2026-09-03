# Contract: Quality-Diversity Selection v1

Inputs are the canonical problem type, existing active candidate IDs, candidate archive records,
candidate source files for bounded token novelty, island capacity, and configured RNG seed.

Invariants:

- evaluator `validity` is the first ordering dimension;
- evaluator `combined_score` remains the quality dimension;
- the best valid candidate is selected before diversity representatives;
- only exact canonical family tags create family representatives;
- each protected family contributes at most one candidate;
- no selected ID occurs twice or exceeds island capacity;
- invalid candidates never displace a valid candidate;
- final result remains `CandidateArchive.best()`, independent of active-set diversity;
- missing/malformed metadata yields the legacy ordering fallback;
- the policy invokes no model, command, evaluator, or service.
