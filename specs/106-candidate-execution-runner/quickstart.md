# Quickstart

Feature 106 is an offline execution boundary for one already admitted candidate. A future API
will be shaped like:

```python
result = run_candidate_execution(
    plan=plan,
    admission=admission,
    workspace_root=materialized_workspace,
    input_root=staged_input_path,
    expected_admission_sha256=admission.digest(),
    attempt_id="attempt-0001",
)
```

The runner rechecks the private workspace and staged input bytes, starts the plan's absolute
argv followed by the bundle entrypoint with `shell=False`, and supplies
`LUNAR_CANDIDATE_INPUT_ROOT` for read-only input access.
The returned object contains status and bounded telemetry only. It does not call an evaluator,
write a receipt, create a Candidate, or initialize Store/home state.

Implementations and tests must use local deterministic fixtures; do not run OpenEvolve, WebAgent,
models, providers, remote services, or campaigns. A successful process exit is not an accepted
score and cannot be used as Lunar ranking evidence.
