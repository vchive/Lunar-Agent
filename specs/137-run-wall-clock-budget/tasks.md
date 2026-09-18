# Tasks

- [x] T001 Freeze the run-level deadline, timeout-clipping, failure-precedence, cancellation-race,
      compatibility, and historical-preservation contract.
- [x] T002 Trace `run_agent()`, synchronous `resume()`, concurrent `resume()`,
      `_execute_task()`, `AgentRequest`, `RuntimeAgentAdapter`, and runtime timeout contracts.
- [x] T003 Add one controller-local monotonic deadline per active run execution and route an
      exhausted remainder through the existing `max_runtime_seconds` budget failure path.
- [x] T004 Clip explicit/configured `run_agent()` timeouts and every normal `resume()` runtime
      request to the positive remaining run duration without mutating configuration or policy.
- [x] T005 Preserve one shared deadline across concurrent workers, no post-exhaustion claims,
      post-request budget checks, idempotent failure persistence, and existing artifact semantics.
- [x] T006 Exercise cancellation immediately before/during/after clipped requests, including
      cancellation fan-out, late-result discard, process cleanup, and durable status precedence.
- [x] T007 Add deterministic offline tests for sync/concurrent timeout propagation, exhausted
      admission, explicit delegation timeout, adapter/runtime forwarding, retries, and races.
- [x] T008 Run focused/shared regressions, Ruff, compileall, Specify checks, diff/link checks, and
      an independent Feature 134 byte/SHA inventory. Do not start a provider or campaign.
- [ ] T009 Complete independent review, update `HANDOFF.md` and readiness/roadmap notes, mark this
      SDD complete, commit and push the verified implementation. A future real run requires a
      separate registration and unique slot.
