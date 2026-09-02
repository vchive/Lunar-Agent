# Feature Specification: Evolution Adapter Provenance

**Feature Branch**: `018-evolution-adapter-provenance`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Make detached/resumed evolution runs deterministic with explicit adapter configuration

## Context and scope

Lunar-Agent persists an evolution contract and strategy state, but loop/population state currently
does not identify the generator/evaluator invocation that produced its archive. A resumed process
can therefore be pointed at a different executable, role, or capability set while appearing to be
the same run. This feature records credential-safe fingerprints for the explicit generator and
evaluator adapter profiles and rejects configuration drift before claiming or executing the
evolution task. OpenEvolve's existing command digest remains unchanged.

## User Stories & Testing

### User Story 1 - Resume with the same adapters (Priority: P1)

As a local owner, I want a detached evolution run to resume with the same solver and evaluator
configuration so that its archive remains comparable across process boundaries.

**Independent Test**: Start a detached run, resume it with the same commands/profiles, and verify
that the strategy continues and the stored fingerprints match.

### User Story 2 - Reject adapter drift (Priority: P1)

As a problem owner, I want a resume with a changed executable, role, name, or capability to fail
before the task is claimed, so a stale archive cannot be silently mixed with new evidence.

**Independent Test**: Change one adapter command/profile after a checkpoint and assert a clear
configuration-mismatch error and no new candidate.

### User Story 3 - Preserve legacy and library callers (Priority: P2)

As an existing caller, I want `EvolutionConfig` and old state files without provenance fields to
remain readable, while new CLI command-backed runs opt into fingerprints automatically.

**Independent Test**: Run callback-only library strategies and load a legacy state fixture without
new fields; existing evolution and OpenEvolve tests remain green.

## Functional Requirements

- **FR-1801**: `EvolutionConfig` MUST support optional credential-safe generator and evaluator
  fingerprints without storing raw command arguments.
- **FR-1802**: A CLI loop/population run using an explicit generator or Agent solver MUST persist a
  generator fingerprint; an explicit command or Agent evaluator MUST persist an evaluator fingerprint.
- **FR-1803**: A fingerprint MUST cover the command argument vector and declared adapter identity
  (name, role, and sorted required capabilities) using a canonical SHA-256 representation.
- **FR-1804**: Resume MUST compare stored and requested fingerprints before claiming the SQLite task
  or invoking a strategy. Any mismatch MUST fail closed with no new candidate or state mutation.
- **FR-1805**: Callback-only library callers and OpenEvolve command behavior MUST remain compatible;
  omitted fingerprints remain optional and old state payloads remain readable.
- **FR-1806**: Fingerprints, state, and errors MUST not contain API keys, raw prompts, or unbounded
  command output.

## Success Criteria

- **SC-1801**: Same-command detached/resume completes with identical archive/config fingerprints.
- **SC-1802**: Changing any explicit solver/evaluator command or profile blocks resume before claim.
- **SC-1803**: Full tests, lint, compile, Spec Kit checks, and existing OpenEvolve fixtures pass.

## Out of scope

- Hashing executable file contents or tracking mutable dependencies outside the explicit command.
- Discovering agents from PATH, Hermes/OpenCode/OpenClaw configuration, or remote services.
- Changing candidate ranking, evaluator semantics, or SQLite schema.
