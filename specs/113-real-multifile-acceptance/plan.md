# Implementation plan

Use two tiny optimization problems with two JSON inputs and two JSON outputs. A feasible
suboptimal result remains valid; an independent exhaustive oracle supplies the optimum gap.
`measurement/tasks.py` owns the task text, fixtures, checkers and twelve holdouts per task.
Holdouts and reference results are never inserted into compiler or solver prompts.
Each task has two feasible probes on the registered input instance and one feasible probe with
changed input values. Report the changed-input row as a synthetic input-adaptation check, not
evidence of solving an additional real task; compare combined-score ordering only within the
same input instance. Python file count is structural evidence, not proof of helper execution.

`runtime_guard.py` observes the native runtime's complete calls across intake, evaluator compiler,
auditor and candidate turns. It persists request starts and sanitized outcomes before returning,
uses one shared counter, and passes credentials in memory only. Native request bodies, parsing and
solver algorithms are unchanged. The explicit GLM-5.2 model uses the same gateway hash as 069/082;
the current CC Switch default model is not inherited. Provider decoding failures can hide usage,
so records distinguish known counters from complete consumption. No price is assumed.

`campaign.py` registers byte hashes and executes exclusively owned slots in separate process
sessions. A supervisor enforces total wall time, terminates observed descendant processes on
timeout, and preserves the unfinished slot. A second invocation cannot reopen a campaign.
`worker.py` stages only public task inputs and invokes the installed native CLI. Analysis uses
the saved contract, preparation and delivery, never regenerates or resumes product work, and
runs holdouts in separate snapshots.

## Data model and decisions

- `manifest.json`: immutable source/measurement/runtime pins, fixed cases, schedule and ceilings.
- Private `.lunar/acceptance113-20260916/`: campaign marker, slot start/end records, calls JSONL,
  native Store/workspace, stdout/stderr, CLI JSON and independent audit snapshots.
- `postrun/`: sanitized per-slot results, local artifact hashes and concise report. Missing results
  stay missing; no fabricated zero-quality values or pooling across tasks/configurations.

`delivery_completion` records the independently verified product output. `primary_valid_completion`
also requires normal supervisor/worker completion. `registered_valid_completion` additionally
requires the recorded model/budget envelope to be verified, including complete known usage.
These remain separate so incomplete telemetry neither erases an observed feasible delivery nor
becomes evidence of staying within a consumption budget. Non-primary quality/gap stay null;
`output_check` is explicitly a provisional diagnostic for all slots.

The provider uses server defaults for sampling/thinking; native code does not send temperature,
max_tokens or reasoning_effort. The local tool loop has four tool steps per invocation, no memory,
no retained session history, and no run_command tool. The fixed population has two initial
candidates and one offspring, one island and one round, seed 113. These are at most three
candidate proposals, not three independent task attempts.

## Complexity and limits

Campaign guard/supervisor are measurement instrumentation, not a new product cancellation API.
Local tools and Python execution are not an OS sandbox. The holdout implementation is in this
checkout but is not supplied as task context; no claim of cryptographic secrecy is made.
Two hand-authored cases and one attempt each cannot establish generalization or a model ranking.
Product full regression already passed at `c977eb4`; run focused campaign tests, current local
quickstart, Ruff, compilation, Specify and frozen-history diff checks for this measurement increment.
