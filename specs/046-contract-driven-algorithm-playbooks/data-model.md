# Data Model: Contract-Driven Algorithm Playbooks

## Algorithm playbook

```json
{
  "schema_version": "1",
  "problem_type": "routing",
  "mode": "diversify",
  "objective_direction": "minimize",
  "family_tag": "savings_merge",
  "alternative_families": ["regret_insertion", "two_opt_local_search"],
  "selection_basis": "untried_family",
  "hard_constraint_ids": ["serve-all", "vehicle-capacity"],
  "modeling_checks": ["preserve_atomic_entities", "explicit_depot_and_route_boundaries"],
  "validation_checks": ["replay_each_visit_once", "recompute_objective_from_export"],
  "instruction": "Build one attributable diversify experiment using family_tag; preserve validity and independently replay the listed checks."
}
```

The object exists only inside an Agent generation prompt. `family_tag` is a repository vocabulary,
not an evaluator result. `selection_basis` reports why it was selected. Constraint IDs originate in
the canonical contract; family attempt outcomes originate in independently evaluated experiment
cards. The playbook cannot affect selection, validity, score, or budgets.
