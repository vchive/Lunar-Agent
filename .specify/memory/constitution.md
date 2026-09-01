<!--
Sync Impact Report
- Version change: template → 1.0.0
- Modified principles: replaced all scaffold placeholders with six Lunar-Agent principles
- Added sections: Standalone Runtime Constraints; Development Workflow
- Removed sections: none
- Deferred items: none
-->

# Lunar-Agent Constitution

## Core Principles

### I. Standalone Distribution
Lunar-Agent MUST be installable and usable from this repository without relying on any pre-existing
Hermes, OpenCode, Codex, Python package, model gateway, or user-specific agent directory. Runtime
dependencies MUST be declared and reproducibly installed by the repository. A globally installed
Hermes environment MAY be used only as an explicit development convenience, never as a runtime
requirement.

### II. Local-First and Durable State
Lunar-Agent MUST run as a single-user local application by default. Run state, event history,
checkpoints, and artifacts MUST be recoverable from local storage after a process or terminal
failure. The controller, not an Agent Runtime, is the source of truth for task state.

### III. Runtime Adapter Isolation
Agent execution MUST be accessed through a small, documented Runtime Adapter contract. Hermes is
the first planned runtime implementation, but controller logic MUST NOT depend on Hermes-specific
handles, events, or prompt formats outside the adapter. Replacing a runtime MUST not require
rewriting the planner, scheduler, store, or evaluator.

### IV. Artifact-First and Independently Verified Results
Tasks MUST declare observable acceptance criteria. Large outputs, logs, and generated files MUST be
stored as artifacts rather than kept only in model context or database rows. A task MUST NOT be
marked successful solely because a Worker claims completion; an independent verifier MUST inspect
the declared outputs whenever verification is applicable.

### V. Bounded Autonomy and Explicit Authority
The system MUST enforce tool, filesystem, network, secret, time, and token boundaries. Destructive
or sensitive actions MUST pause for explicit approval unless a user-configured policy grants them.
Missing approval routes MUST fail closed. Local execution is trusted for the owner, but accidental
credential leakage and uncontrolled side effects remain unacceptable.

### VI. Test-First Recovery and Small Surface Area
Every state transition, retry policy, cancellation path, and runtime integration MUST have tests.
Durable events MUST be idempotently consumable, and recovery tests MUST cover interruption during
each long-running phase. The first release MUST prefer SQLite, the local filesystem, a CLI/TUI, and
one background process over distributed services. New dependencies require a concrete recovery,
safety, or user-value reason.

## Standalone Runtime Constraints

- The project MUST provide a documented bootstrap command that creates an isolated environment and
  installs all required Python dependencies.
- The default deployment MUST bind only to the local machine; no public network listener is required.
- SQLite MUST be used for the durable control-plane ledger in the first release, with WAL mode and
  explicit schema migrations.
- A run workspace MUST be isolated by run ID and may be backed by Git checkpoints when source
  changes are involved.
- Model providers MAY be remote or local, but configuration MUST make data egress explicit and
  secrets MUST be kept out of prompts and committed files.
- The evaluator MUST receive only the inputs needed to verify a task and MUST return structured
  evidence, not an unqualified natural-language verdict.
- The repository MUST include a mock/test runtime so core controller tests do not require a model,
  Hermes installation, network, or user credentials.

## Development Workflow

1. Every meaningful change starts with a spec under `specs/` and is traced to acceptance scenarios.
2. The plan MUST record decisions, alternatives, data model, contracts, and a runnable quickstart.
3. Tasks MUST be dependency ordered and independently testable; the P1 story is the MVP boundary.
4. Implementation MUST preserve backward-compatible data migrations or provide an explicit migration
   and recovery note.
5. Before completion, run unit tests, recovery/idempotency tests, and the quickstart scenario; record
   known limitations in the relevant design document.

## Governance

This constitution supersedes ad-hoc implementation preferences for Lunar-Agent. Amendments require
updating this file, its Sync Impact Report, and any affected feature specs or plans. Versioning uses
semantic versioning: MAJOR for incompatible governance changes, MINOR for new or materially expanded
principles, and PATCH for clarifications. Every implementation review MUST verify compliance with
the principles and explicitly justify any exception in the plan's Complexity Tracking section.

**Version**: 1.0.0 | **Ratified**: 2026-09-01 | **Last Amended**: 2026-09-01
