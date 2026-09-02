# Evolution Strategy Contract

This is the library/adapter contract used by all local strategies.

## Inputs

An implementation receives:

```python
EvolutionContext(
    contract=AlgorithmProblemContract,
    workspace=Path,
    generate=CandidateGenerator,
    evaluate=CandidateEvaluator,
    config=EvolutionConfig,
)
```

`generate(request: GenerationRequest)` returns one draft or a bounded sequence of candidate drafts.
The request contains the isolated iteration, selected parent, inspirations, archive snapshot, and
run workspace. A draft must contain a relative source path and UTF-8 source text.
`evaluate(candidate_path, contract)` returns a validated `EvaluationReport`.

## Outputs

`run()` and `resume()` return the `StrategyResult` JSON shape described in `data-model.md`. The
strategy must persist the candidate before returning and may return `failed` only after preserving
the failure evidence in the archive/state files.

## State and paths

All files are below the run workspace:

```text
evolution/
├── candidates/<candidate-id>/candidate.py
├── candidates/<candidate-id>/record.json
├── archive.jsonl
├── state.json
└── external/openevolve/       # adapter-only scratch space
```

The evaluator path and generated source path are checked for workspace confinement. A strategy must
not write to a parent directory, follow an escaping symlink, or accept an absolute candidate path.

## Selection invariant

Candidates are ordered by `(validity, combined_score)` with validity first. The best candidate is
always a valid candidate, or `null` when none are valid. Invalid candidates remain visible in the
archive and count toward diagnostics, but never satisfy a successful result.

## OpenEvolve adapter contract

The adapter receives an explicit command list, not a shell string. It writes a generated JSON config
under `evolution/external/openevolve/`, sets `cwd` to that directory, enforces a timeout, and expects
the external command to write a bounded `result.json` containing either:

```json
{"candidate_path": "candidate.py", "evaluation": {"...": "..."}}
```

or a candidate path that Lunar-Agent evaluates itself. The adapter imports only paths below the
adapter directory, copies the candidate into the canonical archive, and records the subprocess exit
status. It never treats external stdout as a successful result by itself.
