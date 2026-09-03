# Implementation Plan: Conversational Evolution Handoff

## Technical context

The existing `LocalController` owns SQLite task lifecycle and the filesystem artifact ledger.
`RuntimeContractCompiler` and `solve` own intake; `create_evolution_run`/`run_evolution` own
strategy execution. The implementation will add a narrow bridge in the CLI/controller boundary,
not a second strategy implementation.

## Decisions

1. Keep intake and evolution as separate durable runs linked by one idempotent event. This avoids
   changing the task schema or allowing strategy state to bypass the controller ledger.
2. Supersede generated DAG tasks only after the contract is compiled and only while they are
   unstarted. The intake task and compiler artifacts remain successful evidence.
3. Reuse the explicit solve runtime through two role-bearing adapters. The generator and evaluator
   receive distinct prompts and workspaces, while `EvaluationReport` validation remains the final
   authority.
4. Copy staged inputs through a controller method that validates source ledger metadata and target
   confinement. Never persist the source path or raw runtime configuration in the link event.
5. Make strategy settings opt-in and bounded, with defaults inherited from the contract. Existing
   `evolve CONTRACT` remains the full explicit-adapter surface.

## Data flow

```text
solve goal
  -> compiler/intake run
  -> validated contract + plan
  -> supersede skipped plan tasks
  -> create evolution run + canonical contract
  -> copy verified data/raw artifacts
  -> RuntimeAgentAdapter(solver/evaluator)
  -> loop | population | openevolve
  -> evolution archive/state/result
  -> link/status payloads
```

## Safety and recovery

- Link payloads are bounded scalar metadata and are keyed by a deterministic event ID.
- Input copying uses regular-file and symlink checks, atomic temporary replacement, and digest
  comparison; a mismatch aborts before strategy execution.
- Child evolution remains resumable with its canonical contract and strategy state. The intake run
  can be resumed/polled without creating another child.
- A failed evolution never changes the canonical contract or marks a candidate valid.

## Complexity tracking

- Two runs are intentional: the existing schema has no parent-run foreign key, and introducing one
  would add a migration without improving local recovery for this opt-in bridge.
- Runtime-backed roles use the same runtime instance sequentially in one CLI process. Their role
  prompts, workspaces, and strict report parser preserve the existing evaluator boundary; callers
  needing physically independent providers can continue to use `evolve` portfolio options.
