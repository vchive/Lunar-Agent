# Data Model: Verified Algorithm Candidate Execution

## CandidateExecution

An immutable bounded result returned by a `CandidateRunner`:

```json
{
  "schema_version": "1",
  "status": "succeeded",
  "exit_code": 0,
  "duration_ms": 143,
  "stdout_bytes": 128,
  "stderr_bytes": 0,
  "stdout": "bounded redacted preview",
  "stderr": "",
  "artifacts": ["stdout.txt"]
}
```

`status` is `succeeded`, `failed`, or `timed_out`. Output previews are bounded and redacted. Paths
are portable relative paths below the candidate attempt workspace. A runner can declare additional
regular output files through `execution-artifacts.json`; the controller hashes them as
`candidate_execution_output` artifacts.

## Execution evidence artifact

The runner writes `execution.json` beside the candidate source. It contains the canonical
`CandidateExecution` fields and no executable command arguments or credentials. The controller
indexes it as an execution artifact and passes its relative location to the evaluator wrapper.

## Provenance

Execution-backed strategy state stores only:

```json
{
  "runner_fingerprint": "<sha256>",
  "evaluator_fingerprint": "<sha256>"
}
```

The digest input includes command identity, role/profile, timeout, and capability settings. Raw
commands, endpoint credentials, and output contents are excluded from state.
