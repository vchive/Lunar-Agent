# Feature 116: Accurate input waiting and recoverable bundle preparation

## Problem and outcome

Feature 115 retained a compiled contract after evaluator preparation timed out, but its parent
claimed `awaiting_input` without a question and the CLI returned no run JSON. Dependency waiting
must not accept user answers. Automatic evaluator preparation failures need durable, sanitized
diagnostics and an explicit resume path that reuses the accepted contract.

## Acceptance

1. Only a waiting task with a nonempty input question is pending user input. Dependency waits
   remain scheduler-owned; a stray answer must not create artifacts or release such a task.
   Preserve real clarification, dependency release, cancellation and terminal behavior.
2. Automatic bundle preparation records a start before expensive work and a bounded outcome.
   Observations identify the parent, attempt, stage and safe error category without retaining
   arbitrary provider exception text, credentials or model responses.
3. Solve/resume/answer and status expose known preparation failures with the parent identity,
   no invented user question, and explicit resume guidance only for recoverable errors.
   The command returns nonzero; the compiled contract remains available. No automatic retry.
4. An explicit resume validates existing inputs and evidence before retrying preparation.
   Frozen bundles are reused without compiler/auditor calls; prepared/terminal resume creates
   no extra preparation attempts. Cancellation and integrity failures are not retry promises.
   Recheck parent state between compiler, probes, auditor and publication so a terminal parent
   cannot start a later expensive phase or publish a new preparation after its callback returns.
5. Offline tests cover failure, interruption, explicit recovery and old-state compatibility.
   No provider requests or changes to frozen 113/115 measurements are included.
