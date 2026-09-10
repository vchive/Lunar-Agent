# Feature 069 interim observation: slot 2

Observed on 2026-09-10 at 10:34:07 +0800. This is a partial observation. Slot 1 was still running;
slots 3/4 were waiting for the fixed wave barrier. No final campaign comparison is available.
The machine-readable evidence is in `interim-slot-002.json`.

## What happened

The staged postal-pickup attempt ended during master planning. The subject exited with code 2
after 300.255 seconds; its native logical-run record reports 300,274 ms and `process_nonzero_exit`.
The independently collected diagnostic is `stage=model`, `code=timeout`, with 15 observed model
responses and 19 tool calls. The registered master deadline is 300 seconds. This was not exhaustion
of the 5400-second aggregate window or the 5430-second outer process limit.

No validated `master.json`, build transcript, checkpoint, subject receipt or harness invocation was
created. The last durable workflow state remains `master_running`, with `resume_used=false`.
Its initial zero counters do not mean zero consumption: master usage is persisted only after the
master invocation returns successfully. Full failed-request usage and all scores remain null.

The worker and outer slot process returned zero because they successfully recorded the failed
subject outcome. Those process results do not indicate a successful solution. The native
state/record/report and worker outcome hashes, configuration and single attempt were independently
checked. This slot remains in the fixed denominator, with no replacement or restart.

## What the recorded tool rounds show

The master transcript has one system message, one user message, 15 assistant tool-call messages
and 19 paired tool results: 4 `list_dir`, 6 `read_file`, and 9 `run_command`. No final planning text
was returned. Exactly three tool results report errors:

- A preview of `case/data/opi_points.csv` rejected UTF-8 decoding. The complete 28,878-byte file is
  valid UTF-8; the 20,000-byte preview cuts through a character at offsets 19,998–20,000. This is an
  artificial preview-boundary defect, not evidence of a malformed source file.
- Two `run_command` calls provided the nested `command` as a JSON-array-encoded string. The tool's
  string path uses `shlex.split`, producing executable `[python3,` and `FileNotFoundError`.
  The published tool schema already supports and recommends a real argv array. The runtime retains
  the supplied nested value's type; it did not turn an actual array into this string.

No recorded command was replayed during analysis. The transcript has no per-tool timestamps, and
the last model request did not return complete usage. These three errors cannot be assigned a
precise time cost or treated as the sole cause of the whole planning timeout.

## Next work

Keep the registered measurement unchanged through both waves. This slot did not reach build or
continuation, so it provides no measurement of continuation's effect on candidate quality.

The deterministic UTF-8 defect is being addressed separately as Feature 070 in
`.lunar/worktrees/feature070-utf8-prefix`, branch `codex/read-file-utf8-prefix`. Its scope is a strict
complete-character preview, preserving errors for malformed visible data and true incomplete EOF.
Only synthetic offline tests are required. The running checkout remains on the frozen source;
integration waits until this campaign's termination and audit.

Improved feedback for a JSON-encoded command string and a more focused planning stage are separate
possible follow-ups. Neither is part of Feature 070 or a change to the active measurement. Any
future change to planning policy needs a new registration; increasing this slot's deadline or
restarting it is not an analysis step.

Independent verification confirmed both copies of the JSON report are identical and all 20
evidence hashes match. Report SHA256:
`474efe4ffb4f430df7cc7f8fb2954a02a8b0e168848a1464dbbc4dbaa0f835d7`.

Feature 070 was subsequently implemented and independently reviewed in the isolated branch at
`42c7f6e`. Its 45 new boundary/reproduction cases and final 919-test full suite pass. This change
has not been integrated into the active measurement checkout.
