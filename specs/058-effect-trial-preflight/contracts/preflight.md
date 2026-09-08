# Contract: Effect Trial Preflight

Invocation:

```text
lunar-agent effect-preflight <suite.json> <baseline.json> \
  --case-source CASE_KEY=PUBLIC_CASE_ROOT \
  --subject-command "<absolute subject command>" \
  --harness-command "<absolute harness command>" \
  --requested-model MODEL \
  --harness-python /absolute/path/to/python \
  [--harness-import MODULE]... \
  [--harness-package DIST[==VERSION]]... \
  [--model-profile profile.json] \
  [--subject-env NAME]... [--harness-env NAME]... \
  [--output preflight.json] [--json]
```

The command validates the selected suite and baseline through the existing Feature 048/049
schemas. It checks the selected public source roots against the suite ledger, command executable
files, requested model/profile identity, and explicit environment names. It never prints or stores
the values of those environment variables.

Historical comparators may carry `provenance: {"source": "company-platform", "adapter":
"agentserver"}`. Source must match the baseline's `source`, and adapter must be `webagent`,
`agentserver`, or `company-platform`. Preflight preserves this identity without reporting scores.
Normal/deep trial reports use `baseline_historical_best`; the WebAgent score alias is limited to
explicit WebAgent provenance and the legacy `fm-eval` no-provenance compatibility path. Reproject
the existing company export offline with `effect-baseline --adapter-kind agentserver
--baseline-source company-platform` into a new file; keep the original export for audit.

`--harness-python` must be an absolute regular non-symlink file. The command runs that interpreter
with `-I -B` and a short bounded `-c` probe. `--harness-import` checks import resolution only;
`--harness-package` checks installed distribution metadata and an optional exact `==VERSION`.
Nested module checks resolve components without executing parent initializers. Modules exposed
only through dynamic package initialization fail closed. Command files must have execute permission.
For the current supply-chain extractor, the owner should request at least:

```text
--harness-import anyio \
--harness-import claude_agent_sdk \
--harness-package claude-agent-sdk==0.1.81
```

The built-in harness command must contain `--python <same path>` (or its `--python=<path>` form),
so the checked interpreter cannot be replaced by a `PATH` default. The probe does not import or
execute `tests/extractor_agent.py` or `tests/evaluator.py`; it only proves the interpreter has the
owner-declared modules/distributions available.

On success the report is a bounded object with `schema_version: "1"`, `status: "ready"`,
`suite_sha256`, `baseline_sha256`, selected case/public-file digests, profile digest (or null),
subject/harness command fingerprints, explicit environment names, interpreter fingerprint, and
dependency observations. It contains no score, private root path, raw command line, environment
value, API key, extractor output, or evaluator output. `--output` refuses an existing file and
uses an atomic write. A report is point-in-time evidence; trial commands must repeat their own
validation and must not treat a stale report as permission to run.
