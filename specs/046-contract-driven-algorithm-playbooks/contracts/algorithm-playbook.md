# Contract: Algorithm Playbook v1

Required fields:

- `schema_version`: exactly `"1"`.
- `problem_type`: one canonical `AlgorithmProblemContract` problem type.
- `mode`: the Feature 045 search mode.
- `objective_direction`: `minimize` or `maximize`.
- `family_tag`: one tag from Lunar-Agent's ordered repertoire for `problem_type`.
- `alternative_families`: zero to four distinct repertoire tags excluding `family_tag`.
- `selection_basis`: `untried_family`, `least_tried_family`, `target_family`, `parent_family`,
  `verified_improved_family`, `recombination_lineage`, or `repertoire_default`.
- `hard_constraint_ids`, `modeling_checks`, `validation_checks`: distinct deterministic arrays of
  at most eight safe strings.
- `instruction`: bounded static non-executable guidance.

The solver should include `family_tag` in its optional structured experiment `change_tags`. That
declaration identifies intended technique only. It cannot claim improvement and does not influence
the evaluator except by producing candidate code that passes normal execution and scoring.
