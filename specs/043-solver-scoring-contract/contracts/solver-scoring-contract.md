# Contract: Solver-Visible Scoring Authority

## Producer

Only a successfully loaded `frozen-evaluator-bundle-v2` may produce the contract. Production
revalidates bundle file set, modes, canonical evidence, contract/profile identity, and aggregate
fingerprint before returning objective or evaluator bytes.

## Agent workspace

Before invoking a solver Agent, Lunar-Agent creates exactly these guidance files:

- `scoring/objective.md`
- `scoring/evaluator.py`
- `scoring/manifest.json`

They are regular, non-symlink, read-only files. `manifest.json` uses fixed relative paths and binds
the other two files to the verified evaluator bundle fingerprint. The copy is advisory and never
used as the evaluator executable.

## Prompt projection

The `scoring_contract` object contains the full frozen objective, evaluator path/size/digest,
bounded source excerpt/truncation marker, and bundle fingerprint. It must not contain absolute
paths, compiler/audit probes, input profile, raw input/output bytes, or credentials.

## Consumer rule

The solver should treat this as executable scoring documentation: first align required I/O and
hard constraints, then improve the higher-is-better `combined_score`. It must not return an
evaluation report or modify authoritative bundle files. Lunar-Agent independently executes the
candidate and scores it with the parent frozen evaluator.
