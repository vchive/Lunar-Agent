# Implementation Plan: Effect Trial Preflight

## Technical context

`EffectTrialConfig` and `EffectTrialRunner` already validate the frozen suite/baseline identity,
public source ledger, command executables, environment allowlists, and model-profile digest before
starting a run. The new gate should call those validators in a temporary empty validation context,
then add a narrow interpreter capability probe. It must not duplicate score, receipt, or workspace
logic and must not call the trial runner's `run()` method.

## Decisions

1. **Separate command** — expose `effect-preflight` so callers can validate readiness without
   accidentally starting a normal or deep trial.
2. **Exact interpreter is explicit** — require an absolute `--harness-python` and bind the built-in
   harness command's `--python` argument to it. This avoids guessing from `PATH` or probing a
   different interpreter than the one used during scoring.
3. **Probe availability, never install** — use a short-lived `python -I -B -c` process to check
   static import resolution and `importlib.metadata.version`; dotted modules are resolved without
   executing parent initializers. No arbitrary extractor/evaluator import and no
   package manager invocation.
4. **Credential-safe report** — retain command/environment names and hashes, package versions,
   module availability, and profile/suite/baseline digests; omit raw command arguments, paths,
   env values, profile content, process output, and scores.
5. **Atomic optional output** — stdout is the default transport. `--output` is opt-in and uses a
   bounded exclusive temporary file, flush/fsync, and no-overwrite hard-link publication, refusing
   existing files, concurrent destinations and symlink components.
6. **No trial identity migration** — preflight is an advisory readiness artifact. Trial commands
   still perform all existing checks at execution/resume time and do not trust a stale report.

## Data flow

```text
CLI args
  -> explicit env-name lookup (values stay in memory)
  -> EffectTrialConfig + read-only EffectTrialRunner validation
  -> exact harness-python path/digest + --python binding
  -> bounded metadata/import probe in a clean interpreter
  -> credential-free PreflightReport
  -> stdout and optional atomic report file
```

## Module changes

- Add `famou.effect_preflight` with bounded dependency-spec parsing, interpreter probing,
  report validation/serialization, and a `run_effect_preflight` entry point.
- Add `effect-preflight` parser and dispatch in `famou.cli`; reuse `_parse_command`,
  `_effect_mapping`, `_effect_environment`, and `_load_model_profile`.
- Export the preflight error/report/runner symbols from `famou.__init__`.
- Add focused tests for ready reports, suite/source failures, missing env, profile changes,
  command/interpreter binding, missing imports, package version mismatch, output atomicity, and
  the no-trial/no-credential boundary.
- Document the command and its limitations in README and the harness/preflight contract.
- Add explicit baseline source/adapter provenance to the offline converter and preserve it in
  normal/deep reports. Use the generic historical-best field for company baselines, retaining the
  WebAgent alias only for explicit WebAgent provenance or old adapter-free FM-Eval baselines.

## Verification

- Run focused preflight, effect-trial, deep-effect, and CLI tests.
- Run full `uv run pytest -q`, `uv run ruff check src tests`, `uv run python -m compileall -q src`,
  `uv build`, Specify prerequisites, and `git diff --check`.
- Use the existing company-platform baseline with explicit AgentServer provenance. Probe the real
  public kit when the declared runtime environment is available; no new WebAgent run or export is
  required for this descriptive comparison. A ready fixture is not a real effect result.
