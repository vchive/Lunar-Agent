# Tasks: WebAgent-Normal Workflow Checkpoints

- [x] T069-01 Review this SDD against Feature 068 authority, receipt, and privacy boundaries.
- [x] T069-02 Define and validate bounded master/checkpoint/state schemas and transition table.
- [x] T069-03 Implement the opt-in same-process staged controller around AgentLoopRuntime and SessionTranscript.
- [x] T069-04 Add offline tests for cooperative interruption, one-resume, budget carry-over, and redaction.
- [x] T069-05 Preserve EffectTrialRunner harness gating and add staged subject/CLI integration tests.
- [x] T069-06 Pre-register a two-arm, fixed-denominator measurement and independently audit its manifest.
- [ ] T069-07 Run the registered measurement, summarize per case, update HANDOFF, and publish audit evidence.

The 2026-09-10 integration replaces the earlier standalone fake-runner seam with actual AgentLoop
stages. The model-generated master plan is validated and passed to a fresh build transcript. A typed
cooperative boundary can resume once in the same process, with one ledger and absolute aggregate
deadline. Final runtime metadata includes all stages. Unknown/rejected provider consumption, hard
timeout, transcript failure, changed checkpoints or repeated startup fail closed. Process-death
recovery is explicitly deferred; accepted-only snapshots cannot safely restore unknown spending.

The opt-in API is `run_subject_adapter(workflow_config=StagedWorkflowConfig(...))`; the CLI exposes
`effect-subject --workflow-config PATH`. The unchanged normal receipt builder and EffectTrialRunner
public-projection/receipt gate remain authoritative. No default workflow or historic campaign changed.

Offline coverage includes real AgentLoop + deterministic models, frozen configuration identity,
master-plan propagation, transcript pairing and immutable snapshots, aggregate usage/cost/model
telemetry, deadline carry-over, output retention, symlink replacements, duplicate/resumed invocation,
and the trial gate with a fixture harness. No real provider, WebAgent, or private harness was called.
Real measurement results and a measured claim about solution quality remain pending.

Verification on 2026-09-10: 828 full-suite tests passed (30.94 seconds), including 101 staged-focused
cases; `ruff check src/famou tests` and `git diff --check` passed. The command uses
`pytest -o addopts='' -q` so the terminal summary retains the explicit pass count.

T069-06 completed on 2026-09-10: see `measurement/README.md`, frozen `manifest.json`,
`prelaunch-audit.json` and `dry-run.json`. Four fresh slots (two cases × M/S), two fixed waves,
one attempt each; GLM-5.2, 5400 seconds / 200 tools / 8,000,000 tokens. Product source remains
`80f5af1`. Registration SHA `07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e`.
The independent actual-evidence audit and 26-check isolated dry-run passed without model calls;
874 full-suite tests, Ruff, Specify prerequisites and diff checks passed. No historical campaign
or default workflow changed. Commit registration before launch; T069-07 remains open.

T069-07 started: registration commit `454b521` was pushed before first dispatch at
2026-09-10 10:19:43 +0800. Slots 1/2 have subject-started evidence; slots 3/4 are queued behind
the fixed wave barrier. `measurement/launch-observation.json` is an initial observation, not a
result. The detached campaign process owns both waves; never relaunch. Final outcome audit pending.

Postrun analysis added on 2026-09-10 without changing the frozen product, dispatcher or tests:
`postrun/audit.py` checks actual private case/harness bindings through each original worker,
committed source blobs and import location, frozen/history hashes, unique attempts, phase/wave
ordering and native evidence/receipt links. `postrun/render_report.py` preserves null and scores
above one and verifies descriptive historical references against their pinned originals. Neither
tool dispatches, restores records, loads credentials or writes campaign evidence. Independent
read-only review found no blockers; 29 analysis tests, Ruff and diff checks passed.

The saved actual observation `postrun/observations/20260910T030511Z.json` (and `.md`) verifies
155 evidence files but remains incomplete: slot 1 running, slot 2 failed at the 300-second master
model deadline, slots 3/4 queued. Final mode correctly rejects this partial state. T069-07 stays
open until four terminations, final native summary and independent result/process review. Seal
final audit/report before integrating Features 070/071; do not rewrite frozen historical inputs
after the current source changes.

2026-09-10 11:14 +0800: slot 1 completed with accepted exact harness validity 1 and
overall/quality 0.999999. Subject elapsed 3068.032 seconds, harness 122.493 seconds; subject
usage 869277 tokens and 30 model interactions, excluding extractor usage; cost remains null.
Independent receipt/state/record/report/outcome and actual private-harness review passed.
Slots 3/4 automatically started at 11:12:53 after both wave-one terminations. New partial
observation `postrun/observations/20260910T031419Z.json` and `.md` covers 185 evidence files;
`postrun/slot-001-success.md` records the success interpretation. T069-07 remains open.

2026-09-10 11:18 +0800: slot 3 also terminated at the 300-second master model deadline
(subject 300.222 seconds, exit 2; native 300237 ms; diagnostic model/timeout, 7 model responses,
11 tools). Both staged slots are now failed with no accepted receipts or scores, valid 0/2;
neither reached build/resume. Slot 4 normal remains unresolved, so the campaign is not final.
`postrun/observations/20260910T031858Z.json` and `.md` verify 196 evidence files. Product source,
dispatcher and original tests stay frozen until the last registered attempt terminates and
final evidence is sealed; no repair integration, replacement attempt or campaign relaunch.
Independent slot 3 review also verifies 11 unique call/result pairs (read_file 4, list_dir 3,
run_command 4), with one nested-JSON argv string causing FileNotFoundError. No validated master
plan, build transcript, checkpoint file or harness exists. The initial workflow counters are
not zero spending, and missing per-tool timing prevents attributing the entire timeout to that
one error. The bounded projection and 17 hashes are in `postrun/observations/slot-003-master-failure.json`.

Additional read-only terminal-master analysis is in `postrun/master-behavior-analysis.md` and
`.json` (16 evidence hashes). Neither master successfully returned and persisted a final response, so these are not observed
plan-schema rejections. Distinct direct file/directory reads and repeated Python data inspections
show exploration, with self-corrected command errors and no observed solver implementation.
Runtime code provides invocation remaining time on request copies, not persisted transcript;
missing historical budget tags do not prove that the model lacked a deadline hint. These findings
inform a later role/handoff SDD; role mixing is an unproven explanation, and network/queue/generation
latency cannot be separated. Local evidence cannot prove that the provider never generated final
text. Slot 4 and all current experiment boundaries remain unchanged.
