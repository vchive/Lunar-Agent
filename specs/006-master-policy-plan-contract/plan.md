# Implementation Plan: Master Policy and Plan Contracts

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from
`/specs/006-master-policy-plan-contract/spec.md`

## Summary

Implement the WebAgent v2.5 Master layer as a small, local, runtime-neutral control-plane contract:
an explicit policy decision, immutable versioned plan documents, optimistic patches/replans, and
verified delivery decisions. The existing controller remains the only scheduler and owns recovery;
the new policy layer does not introduce a WebAgent-style fixed lifecycle or any service process.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library; `pytest` and `ruff` are development-only

**Storage**: Existing SQLite WAL ledger; existing run-scoped local filesystem artifacts

**Testing**: `pytest`, controller/store/CLI integration fixtures, and Python 3.11/3.12/3.13 checks

**Target Platform**: macOS and Linux local workstations

**Project Type**: Installable Python CLI/library

**Performance Goals**: Policy/plan retrieval under one second for 10,000 events and 100 revisions;
100 plan revisions remain locally inspectable without a service

**Constraints**: Local single-user control plane; no HTTP/SSE, remote queue, global Hermes/OpenCode/
Codex discovery, secrets in durable records, or mandatory model dependency

**Scale/Scope**: One local controller writes one run at a time; patch/replan supports idle or failed
runs, but deliberately fails closed while a task is executing or awaiting input

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Standalone Distribution: PASS — no new host-Agent dependency or network listener.
- Local-First and Durable State: PASS — plan revisions and decisions live in the existing SQLite
  ledger; evidence points to run-local artifacts.
- Runtime Adapter Isolation: PASS — policy and plan types do not import a runtime or model client.
- Artifact-First and Independently Verified Results: PASS — delivery consults task evaluation events
  and hashed run artifacts, rather than a worker's free-form claim.
- Bounded Autonomy and Explicit Authority: PASS — questions, rationale, evidence, patch operations,
  and JSON payloads have bounded validation; secret-like values are rejected.
- Test-First Recovery and Small Surface Area: PASS — standard-library types and an additive SQLite
  migration; contract tests precede implementation.

## Research Summary

See [research.md](./research.md). The selected design adopts WebAgent's high-value effects—Master
routing, structured clarification, plan provenance, independent verification, and explicit
patch/replan lifecycle—while excluding its OpenCode-specific agents, HTTP/SSE service plane, remote
evolution service, and mandatory fixed phases.

## Project Structure

### Documentation (this feature)

```text
specs/006-master-policy-plan-contract/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   ├── policy-decision.md
│   ├── plan-document.md
│   └── plan-patch.md
├── quickstart.md
└── tasks.md
```

### Source Code (repository root)

```text
src/famou/
├── policy.py        # policy, plan, patch domain validation and application
├── models.py        # durable run/task status additions
├── store.py         # SQLite plan revisions, decision records, atomic revision updates
├── controller.py    # planned-run creation and verified delivery selection
└── cli.py           # decide, plan, patch, replan, and deliver JSON commands

tests/
├── test_policy.py   # domain contract/unit tests
├── test_plan.py     # scheduler and revision integration
├── test_store.py    # atomicity, migration, and optimistic concurrency
└── test_cli.py      # parent-Agent JSON contract
```

**Structure Decision**: Keep policy domain validation in one dependency-free module, retain SQLite
queries in `Store`, and keep CLI formatting at the boundary. This preserves the current small
surface area and means a Hermes, Codex, OpenClaw, or built-in runtime can use identical plans.

## Phase 0: Research

1. Use the WebAgent branch findings to separate effect-layer techniques from service-only machinery.
2. Adopt immutable local plan revisions with optimistic base-version checks rather than a remote
   lifecycle service.
3. Preserve the current physical task table while mapping plan-local task IDs to safe unique task
   IDs; this avoids a destructive database rewrite and lets legacy JSON plans remain compatible.

## Phase 1: Design

1. Define `PolicyDecision`, `PlanDocument`, `PlanTask`, `PlanPatch`, and plan-revision records.
2. Add SQLite tables for plan versions and decisions plus a current-plan pointer on a run.
3. Document JSON CLI contracts for policy inspection, plan lookup, patch/replan, and delivery.
4. Define a safe revision boundary: no revision while work is `running` or awaiting input; completed
   task definitions remain immutable; removed not-yet-run tasks become `superseded`.

## Phase 2: Implementation

1. Write policy/plan validation tests before the new domain module.
2. Add the additive storage migration and atomic planned-run/revision operations.
3. Adapt controller and CLI commands without altering the `Runtime` protocol.
4. Add status visibility, verified delivery selection, documentation, and regression coverage.

## Post-Design Constitution Check

- Standalone Distribution: PASS — no package, daemon, service, or system-level integration added.
- Local-First and Durable State: PASS — current version pointer and immutable prior versions are
  transactionally stored in the local ledger and survive restart.
- Runtime Adapter Isolation: PASS — `MasterPolicy` is deterministic/injectable and never controls a
  runtime directly.
- Artifact-First Verification: PASS — only succeeded runs with successful `task_evaluated` events
  and indexed artifacts can yield a `deliver` decision.
- Bounded Autonomy: PASS — no arbitrary JSON merge; operations are typed, validated, bounded, and
  fail closed for concurrent active work.
- Test-First Recovery and Small Surface Area: PASS — additive migration and test-first fixtures;
  legacy simple plans retain their existing execution contract.

## Complexity Tracking

No constitution violations. A physical/logical task-ID mapping is intentionally contained in the
storage layer: it preserves compatibility with the existing globally keyed `tasks` table while
allowing a plan to retain readable local task IDs across versions. Plan revisions are keyed by
`(run_id, version)` so reusable plan template IDs can safely appear in multiple runs.
