# Feature 111: Conversational multi-file evolution and parent delivery

## Outcome

Users can start multi-file evolution from normal `solve --evolve` with an explicit fixed bundle
profile. The existing runtime compiles the task, generates full source bundles and returns the
selected source, independently scored outputs and report through the parent task's delivery flow.

## Acceptance

1. `solve --evolve --bundle-profile PROFILE` uses the normal intake/runtime and the 110 Agent
   bundle generator. Legacy solving and single-file evolution remain compatible. Conflicting
   evaluator/producer modes fail before model/compiler work; bundle mode uses native population.
2. Profile targets match the complete parent input ledger at `data/raw/<target>`, including exact
   size/hash. The effective pipeline reads parent-staged copies, not unrelated external input.
   A semantic profile digest records settings and pins without storing private source paths.
3. Resume/answer require the same mode/profile even when `--evolve` is omitted. Reciprocal parent/
   child links, contract and child workspace must match before handoff mutations or delivery.
4. The selected bundle's already scored snapshot enters normal parent output/delivery results.
   Retain complete source and evaluation materials in a pinned portable copy. Do not rerun the
   winner or invoke an Agent evaluator while delivering. Use existing output publication/Store.
5. Terminal replay reuses the prepared delivery and published outputs without another Agent,
   candidate or evaluator call. Drift, conflicting bytes, cancellation and budget violations are
   rejected; partial delivery publication is reconciled with existing failure/rollback semantics.

## Scope

The compiled contract retains the existing requirement for at least one declared output; optional
outputs may be absent. The evaluator profile remains explicit; automatic evaluator preparation, generic producer bundle
imports and active-process cancellation orchestration remain later work. No new attestation,
database schema or real model/framework effectiveness measurement. Completed verified code is
committed and pushed under the user's current instruction.
