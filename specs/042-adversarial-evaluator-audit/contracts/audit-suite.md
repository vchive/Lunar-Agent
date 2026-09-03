# Contract: Adversarial Evaluator Audit Suite

## Producer

A fresh runtime invocation receives the canonical problem contract, private structural input profile
and digest, evaluator objective, and evaluator source. It does not receive compiler-generated probes
or any solver/search evidence.

## Response

Return exactly one JSON object with:

- `schema_version="1"`;
- exact `constraint_coverage` for all hard constraints;
- one `expected_validity=0` probe per hard constraint with the matching `constraint_id`;
- at least two global `expected_validity=1` probes with `constraint_id=null`;
- at least one `score_order` pair referencing two distinct valid probes.

Each probe contains bounded unique relative files only below `data/raw/` or `output/`. The response
cannot contain markdown, credentials, absolute paths, commands, evaluator replacements, or prose.

## Admission

Lunar-Agent reconstructs each workspace, adds canonical successful `execution.json`, executes the
already compiled evaluator, and requires:

- exact expected validity;
- an invalid probe's matching constraint code in `error_info`;
- strict `combined_score` ordering for every declared pair;
- one valid `EvaluationReport` within time and output limits.

Any failure rejects and removes the staged bundle before candidate generation.
