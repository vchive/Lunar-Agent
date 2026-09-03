# Implementation Plan: Executable Famou-Bench Adapters

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

Feature 048 already owns suite/baseline validation, public staging, repeated-run recovery, process
separation, and milestone reporting. The missing pieces are executable protocol clients. The
inspected Famou Bench cases expose `tests/extractor_agent.py` and `tests/evaluator.py`; FM-Eval's
current harness runs those two scripts directly rather than `tests/test.sh`. Its analytics results
surface exposes per-run projection/readiness and score fields, but immutable publication,
CaseRevision, evaluation-profile, and harness identities remain supplied by the frozen suite.

## Decisions

1. **Adapters beside the protocol** — add one standard-library `famou.effect_adapters` module. It
   depends on Lunar runtime/tool primitives and Feature 048 identities, never on FM-Eval imports.
2. **Fresh normal session** — subject creates one OpenAI-compatible `AgentLoopRuntime` per process,
   no memory and no transcript. This matches the available shallow WebAgent treatment.
3. **Actual official case** — harness independently recomputes FM-Eval's canonical
   `case-content-v1` identity, matches its public instruction/data to the staged projection, then
   hashes and invokes the case-owned extractor and evaluator. Reimplementing extraction would alter
   the measurement.
4. **Two child environments** — extractor receives only the effect runner's explicit harness env
   plus a minimal base. Evaluator receives only a fresh minimal base. This preserves the SUT/harness
   boundary and the harness's internal credential boundary.
5. **Local results conversion** — baseline conversion is offline. Authentication/export remains an
   owner/platform action; Lunar consumes the resulting JSON and cannot mutate the service.
6. **Suite owns frozen identity** — the converter copies benchmark, evaluation-profile, case, and
   harness identities from the strict suite; it cannot infer historical `1.10.6` from the current
   `agentco-bench-lite` checkout.
7. **Telemetry is nullable** — interaction turns are locally observed. Usage is emitted only when
   every model response provides a valid usage object; missing provider telemetry remains `null`.
8. **No raw diagnostics in receipts** — adapters use bounded in-memory stdout/stderr only to decide
   a stable error state. Receipts contain typed scores/statuses and identity echoes.

## Data flow

```text
Feature 048 public subject request
        -> fresh Lunar Agent loop -> solution files + score-free subject receipt

Feature 048 private harness request + owner case root
        -> verify extractor/evaluator SHA-256
        -> extractor (explicit harness env) -> normalized files
        -> evaluator (minimal env) -> strict score receipt

saved FM-Eval /results JSON + frozen suite + model identity
        -> select/normalize per-run rows -> strict Feature 048 baseline JSON
```

## Runtime changes

`ModelTurn` gains backward-compatible optional response model and usage fields. The
OpenAI-compatible parser validates provider telemetry; one-shot runtime metadata and Agent-loop
metadata expose only normalized strings. Existing two-positional-argument `ModelTurn` callers stay
valid.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No FM-Eval/WebAgent import; optional private scripts remain owner inputs. |
| Local-First and Durable State | Pass | Feature 048 remains the state/recovery owner. |
| Runtime Adapter Isolation | Pass | Uses repository runtime; no machine-wide Agent discovery. |
| Artifact-First Verification | Pass | Official private harness, not subject text, owns score. |
| Bounded Autonomy | Pass | Explicit endpoint/env/case root, hashes, timeouts, and confined paths. |
| Test-First Recovery | Pass | Protocol, telemetry, isolation, and end-to-end tests precede code. |

## Complexity tracking

One standard-library adapter module, three CLI commands, and backward-compatible runtime metadata.
No dependency, database migration, network export client, service write, or evolution change.
