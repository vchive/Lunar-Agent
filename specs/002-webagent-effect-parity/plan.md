# Implementation Plan: WebAgent Effect Parity Core Loop (Superseded)

**Branch**: `002-webagent-effect-parity` | **Date**: 2026-09-01

## Summary

> This plan is retained for history only. Product direction moved to the Hermes-inspired session
> and scheduler in feature 003; no WebAgent stage machine should be implemented from this file.

Add a Master orchestration state machine around the existing durable Controller, then use a local
ReAct loop as the Build-stage Runtime. The model adapter remains responsible only for HTTP and
response parsing; a separate tool registry owns path confinement and command policy; the controller
remains the sole owner of durable state and artifact metadata.

## Design

```text
LocalController (durable Master/Scheduler)
  ├── intake → clarify → plan → build → verify → deliver
  ├── plan/replan files + awaiting_input state
  └── AgentLoopRuntime (Build stage)
        ├── OpenAICompatibleRuntime.complete(messages, tools)
        ├── Build system contract
        └── LocalToolRegistry
              ├── read_file
              ├── write_file
              ├── list_dir
              └── run_command (explicit opt-in)
```

The Master first persists phase transitions and a validated plan. The Build loop then sends structured
assistant/tool messages back to the endpoint. It emits bounded operational events through a sink
installed by the controller, while the final RuntimeResult carries relative tool artifacts for normal
hashing. Tool arguments are never persisted verbatim; command output is bounded before entering model
context or events. The existing evaluator and artifact checks remain the Verify gate before Delivery.

## Constitution Check

- Standalone Distribution: PASS — standard library only, no Hermes discovery.
- Local-First and Durable State: PASS — controller owns events and artifacts.
- Runtime Adapter Isolation: PASS — HTTP parsing, loop, and tools remain separate boundaries.
- Bounded Autonomy: PASS — workspace confinement, opt-in exec, per-command timeout, step limit.
- Artifact-First Verification: PASS — tool files flow through existing artifact hashing.
- Test-First Recovery: PASS — loop, safety, limit, and regression tests precede release.
