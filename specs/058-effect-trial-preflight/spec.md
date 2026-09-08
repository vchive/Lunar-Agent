# Feature 058: Effect Trial Preflight

## Goal

Provide a read-only gate that proves a planned Famou-Bench normal or deep trial can start with
the selected local inputs and runtimes. The gate is useful before credentials are used or a paid
model is called: it validates the frozen suite and baseline, the public case projection, command
executables, explicitly requested environment variables, model-profile identity, and the Python
environment used by the exact harness.

The gate does not run a subject, extractor, evaluator, or trial round. It may persist a bounded
preflight report when the caller explicitly requests an output path; that report contains only
credential-free identities and dependency observations.

## Scope and contract

- Support the owner's existing baseline by preserving optional `provenance: {source, adapter}`.
  The offline converter requires explicit matching evidence for `agentserver` and
  `company-platform`; its default `webagent` mode preserves the historical adapter-free path.
  Reports use `baseline_historical_best` and expose the actual source/adapter. Only explicit
  WebAgent provenance or legacy `fm-eval` baselines without provenance retain the old
  `webagent_historical_best` alias. Current company exports must be reprojected with explicit
  provenance before use; model, suite identities, per-run scores and eligibility are unchanged.
- Add an `effect-preflight` CLI/library surface with the same suite, baseline, case-source,
  subject-command, harness-command, requested-model, model-profile, timeout, and environment-name
  inputs used by `effect-trial` and `effect-deep-trial`.
- Reuse the effect trial validators. Suite and baseline JSON must be regular non-symlink files;
  benchmark, evaluation-profile, selected case, CaseRevision, public ledger, harness identity,
  baseline model, and evaluator-valid historical rows must agree. Every mapped public source file
  must match the frozen size and SHA-256 digest, and source roots must not contain symlink escapes.
- Subject and harness command entries must be bounded argument sequences whose first executable is
  an absolute regular non-symlink file. The report records command fingerprints, never raw command
  arguments that could contain credentials.
- `--subject-env NAME` and `--harness-env NAME` are explicit allowlists. Every named variable must
  already exist in the invoking environment. Values are passed to validation only and are never
  printed or written to the report. Missing names fail before the dependency probe.
- A supplied model profile is parsed with the bounded `ModelProfile` validator, must name the
  requested model, and contributes its canonical lowercase SHA-256 digest. The report records a
  null absence marker when no profile is supplied. Profile credentials, endpoints, and raw JSON do
  not appear in the report.
- The caller supplies the absolute `--harness-python` used by the exact harness command. The
  preflight checks that it is a regular non-symlink file and probes it in an isolated `-I -B`
  interpreter process. Repeated `--harness-import MODULE` entries must resolve with
  static component-by-component import resolution without executing package initializers;
  repeated `--harness-package DIST[==VERSION]` entries must have
  installed distribution metadata and, when a version is given, an exact match. The probe may
  inspect metadata and import resolution only; it must not execute the extractor/evaluator or
  contact a model endpoint.
  Children exposed only by executing a package initializer cannot be proven available by this
  static check and fail closed.
- The built-in `effect-harness` command must bind its `--python` argument to the same resolved
  interpreter checked by preflight. This prevents a passing probe for one environment from being
  silently followed by a trial using another interpreter. Custom harness commands may expose the
  same binding contract explicitly.
- A successful report has a fixed schema and includes suite/baseline digests, selected case keys
  and public-file digests, requested model, profile digest, command fingerprints, environment names,
  harness interpreter digest/version, package observations, import observations, and `status:
  ready`. It contains no scores, private case paths, environment values, API keys, or extractor
  output.
- `--output PATH` writes the report atomically to a new regular non-symlink path. Existing output
  files and symlink components fail closed. Without `--output`, the report is emitted only through
  the normal CLI JSON output. The command exits non-zero on every failed check.
- Running a trial remains independent and repeatable. `effect-trial` and `effect-deep-trial`
  continue to revalidate their own inputs; a preflight report is evidence of the checks at one
  point in time, not proof that files, environment variables, credentials, packages, or endpoints
  cannot change afterward.

## Acceptance criteria

1. A valid fixture produces a `status=ready` preflight report without creating a trial workspace,
   subject receipt, harness receipt, score, or model request.
2. Suite, baseline, case source, command executable, profile digest, or harness interpreter
   mismatches fail closed with a bounded diagnostic and no output report.
3. Missing allowlisted environment variables fail before any dependency probe; no variable value
   appears in stdout, stderr, or a persisted report.
4. Missing imports and distribution-version mismatches are detected using the exact harness
   interpreter, including `claude-agent-sdk==0.1.81` when requested by the owner.
5. The dependency probe does not run extractor/evaluator code and does not require model
   credentials. Probe output is bounded, deterministic apart from observed interpreter/package
   versions, and contains no absolute private paths.
6. Existing normal/deep effect-trial behavior and no-profile behavior remain compatible; all
   repository quality gates pass.
7. Company-platform baselines yield the same historical maximum from eligible per-run rows in
   both trial modes, retain source provenance, and emit no WebAgent-specific score label. Manual
   best scores, duplicate runs, identity mismatch and conflicting adapter evidence fail closed.

## Out of scope

- Starting a model request, subject process, extractor, evaluator, or evolution round.
- Installing, upgrading, downloading, or resolving Python packages.
- Proving that a model endpoint accepts a request without making a model request.
- Proving an OS sandbox, network policy, credential validity, WebAgent parity, suite parity, or
  benchmark superiority.
