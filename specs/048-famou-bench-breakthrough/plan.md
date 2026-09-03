# Implementation Plan: Frozen Famou-Bench Breakthrough Trial

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

Lunar already has a strategy benchmark, but that measures candidate evolution under an
`AlgorithmProblemContract`. The available Famou result is instead an FM-Eval normal-Agent
experiment. WebAgent source confirms two distinct flows:

```text
normal: famou-master -> famou-build -> deliver
deep:   explicit /evolve -> famou-evolution -> famou-evo-builder -> outer continuation loop
```

`opencode/tools/init_evolution.ts` declares `budget.default(5)`, so five is the source-authoritative
no-argument deep-evolution budget. No evaluated deep baseline exists. Feature 048 therefore adds a
new `famou.effect_trial` module beside `famou.benchmark` and never enters an evolution strategy.

## Decisions

1. **Small frozen slice** — require exactly one or two cases and 1–10 Lunar runs per case. This is
   affordable evidence, not a surrogate 20-case suite score.
2. **Historical best is derived** — ingest per-run FM-Eval receipts and derive WebAgent's best valid
   score. A caller cannot type only a convenient target number.
3. **Exact identity before score** — benchmark release/publication, evaluation profile, case
   revision/digest, extractor digest, and evaluator digest must agree before any comparison.
4. **Public projection only** — Lunar places only manifest-ledger public files in the subject tree.
   The harness command owns its private evaluator/extractor material outside that tree. This is
   capability separation, not an OS sandbox; post-run digest checks detect mutation, while hostile
   same-user commands require an owner-provided sandbox.
5. **Two subprocess capabilities** — subject and harness use separate explicit commands and env
   allowlists. The subject config contains neither baseline scores nor harness credentials.
6. **Normal-mode attestation** — the subject receipt must echo `mode=normal`; the outer runner does
   not call Lunar evolution or WebAgent `/evolve`. A later deep experiment is a separate protocol.
7. **Score and conclusion are separate** — `score_breakthrough` means strict `>` on valid scores.
   The case milestone additionally needs complete planned Lunar coverage and matching identities.
   Baseline eligibility is reported independently; this selected-case best-of-N trial is always
   formally ineligible.
8. **Provider evidence is explicit** — requested/effective model labels and observation level are
   recorded. A matching label with `not_observable` remains descriptive, never provider proof.
9. **Record then resume** — each completed logical run has one immutable atomic `record.json`.
   Interrupted attempts remain; resume starts a new attempt only for the unfinished logical run.
10. **No service coupling** — suite and baseline are local JSON exports. Lunar does not import
    FM-Eval/WebAgent, use their credentials, or mutate the evaluation service.

## Data flow

```text
frozen suite manifest + local public case roots
                       | verify size/SHA-256/private-path fence
              one fresh subject workspace per logical run
                       | explicit normal-Agent command
                 strict subject receipt + solution artifacts
                       | explicit private harness command
                     strict official score receipt
                       | atomic immutable run record
                       v
FM-Eval WebAgent per-run export -> identity validation -> derived historical best
                                                       \
Lunar run records -> coverage/validity/best/telemetry ----> descriptive milestone report
```

## Filesystem and recovery

```text
trial/
  control/suite.json
  control/baseline.json
  control/state.json
  cases/<case>/runs/<NNN>/
    attempts/<NNN>/subject/      # public case projection + subject receipt/artifacts
    attempts/<NNN>/harness/      # generated config + harness receipt only
    record.json                  # immutable logical-run result
  report.json
```

The state identity covers canonical suite/baseline bytes, selected cases, requested model,
run-count/timeout, command fingerprints, and env-variable names. It never stores command text,
environment values, or source-machine paths. Before resume, completed record bytes and every public
source byte are reverified.

## Metrics and interpretation

For each case:

- `valid_rate = mean(validity_score for scored Lunar runs)`;
- `lunar_best = max(overall_score where validity_score != 0)`;
- `webagent_historical_best` is derived the same way from imported runs;
- `score_delta = lunar_best - webagent_historical_best`;
- `score_breakthrough = score_delta > 0`;
- `milestone_achieved = score_breakthrough AND full Lunar run coverage AND shared identities AND
  matching requested/effective model labels`.

The whole-trial milestone is achieved when at least one selected case achieves its case milestone.
It deliberately does not average selected cases into a replacement benchmark score.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Pure standard-library adapter; Famou tools remain optional external commands. |
| Local-First and Durable State | Pass | Local immutable inputs, atomic records, restartable attempts. |
| Runtime Adapter Isolation | Pass | The subject is one CLI contract, independent of Hermes/OpenCode/Codex. |
| Artifact-First Verification | Pass | Only the separate exact harness may produce authoritative scores. |
| Bounded Autonomy | Pass | 1–2 cases, 1–10 runs, explicit commands/env names, bounded timeout/files/receipts. |
| Test-First Recovery | Pass | Identity, isolation, adversarial receipt, and interruption tests precede code. |

## Complexity tracking

One new standard-library module, one CLI command, and exports/documentation. No dependency, SQLite
migration, service, network API, existing strategy change, or automatic FM-Eval publication.
