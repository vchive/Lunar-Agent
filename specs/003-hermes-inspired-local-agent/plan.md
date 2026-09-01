# Implementation Plan: Hermes-Inspired Local Agent Core

**Branch**: `003-hermes-inspired-local-agent` | **Date**: 2026-09-01

## Summary

Keep the existing LocalController/SQLite scheduler as the orchestration boundary and make the
continuous model/tool loop Hermes-inspired. Add an independent local memory store and explicit
memory tools. Do not add WebAgent phase transitions or require a Hermes installation. The
OpenAI-compatible adapter remains a transport boundary; a future Hermes adapter can use the same
Runtime protocol.

## Design Principles

1. **Hermes-inspired, repository-owned** — copy the useful interaction model (persistent session,
   rich local tools, checkpoint memory), not Hermes package internals or global state.
2. **Controller as scheduler** — dependency validation, retries, recovery, artifact handoff, and
   detached process ownership stay in one durable local controller.
3. **Explicit memory egress** — memory is available only when the caller passes `--memory`; notes
   are fetched by an explicit model tool call, never silently appended to an HTTP request.
4. **Replaceable model boundary** — model HTTP parsing, agent loop, tools, and persistence are
   separate modules with small contracts.
5. **Bounded local autonomy** — step/time/output limits and workspace confinement apply to every
   invocation.

## Components

- `memory.py`: SQLite schema, global/run scopes, bounded lexical recall, and note validation.
- `tools.py`: filesystem, optional command, and explicit memory tools.
- `agent_loop.py`: Hermes-style continuous session and bounded tool-call protocol.
- `controller.py`: scheduler/recovery plus runtime event sink and session identity.
- `cli.py`: opt-in flags and detached propagation; stable JSON automation boundary.

## Constitution Check

- Standalone Distribution: PASS — no Hermes import/discovery; standard library implementation.
- Local-First and Durable State: PASS — run ledger and memory live under one configured home.
- Runtime Adapter Isolation: PASS — the model adapter is unaware of memory and scheduling.
- Bounded Autonomy: PASS — command opt-in, no shell, workspace checks, and limits.
- Artifact-First Verification: PASS — all tool-produced files flow through existing artifact hash
  registration and evaluator logic.
- Test-First Recovery: PASS — memory, loop, scheduler, detached propagation, and regression tests
  cover the contracts before release.
