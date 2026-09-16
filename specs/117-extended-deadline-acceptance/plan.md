# Plan

Reuse byte-pinned 113 task/oracle/holdout, runtime accounting and analysis helpers. Fork only the
campaign entry point, worker routing and passive 115 response wrapper into a new directory; the
worker and wrapper preserve their bytes. The new launcher uses 600 seconds in both native CLI
timeout and the clean child environment, and its external supervisor enforces 3600 seconds/task.
Keep 16 requests and the 160000 observed-token threshold, without increasing population size.
The same timeout also bounds a normal Agent invocation: its tool steps share the remaining time,
and each HTTP call is capped by both that remainder and the campaign guard. Thus 16 requests is
an upper limit rather than a promise that all can fit inside the task deadline.

Reference the frozen 115 manifest by SHA-256. Enforce equality of all prior fixed-condition
fields except limits; limits must equal the old mapping with exactly the two declared time changes.
Pin both 113 and 115 historical source/results and reject provider or implementation drift before
launch. A claimed slot remains consumed even on setup failure or unknown cleanup. Unknown cleanup
prevents later launch; it does not remove unstarted tasks from the planned denominator.

The 600-second limit is a bounded allowance for the observed slow reasoning responses, not a
measured latency percentile. The 3600-second task ceiling permits several compilation/generation
stages but still bounds local execution. Alternatives rejected: reopening 115 with larger limits,
changing model/prompt/seed as well, or making repeated requests until one succeeds. No product
changes, dependencies or schema migration; no constitution exception.

Private response prefixes remain at most 64 KiB after credential redaction and are never replayed
to the model. Postrun preparation diagnostics supplement the unchanged independent scoring. A
diagnostic event or model-reported score cannot establish success. Preserve null usage when no
sample exists and report known token subtotals separately from complete total consumption.

Validate registration differences, launch routing/environment, deadline enforcement, fixed
denominators and guard/analyzer behavior offline. Product 116 already passed 5636 tests/1 skip;
measurement-only changes do not require another full product run. Run the local 112 quickstart,
independent prelaunch review, then freeze and push. After both attempts, verify every retained
slot, independently audit available evaluators/deliveries, commit and push the complete findings.
