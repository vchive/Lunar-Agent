# Feature Specification: Solver Scoring Contract

**Feature Branch**: `043-solver-scoring-contract`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Lunar-Agent now executes and independently audits a frozen evaluator before search. The native
Agent solver still receives an incomplete view of that authority. When a persisted
`evolution/contract.json` is present, prompt projection omits both hard and soft constraint arrays.
In compiled-evaluator mode it also withholds the objective text and evaluator implementation that
actually determine ranking. The solver is therefore told to satisfy constraints and improve a
score without seeing the complete rules.

WebAgent/OpenEvolve expose their frozen harness to the candidate builder so it can first align I/O
and feasibility, then optimize the real metric. This feature carries that effect into Lunar-Agent
without exposing compiler/auditor probes or moving scoring authority into the solver. Every Agent
generation receives the complete canonical constraint contract plus a read-only, fingerprinted
projection of an already verified compiled evaluator. Independent execution and evaluation remain
the only admission boundary.

## User stories and acceptance scenarios

### User Story 1 — Generate against the complete problem contract (P1)

1. Every native Agent solver prompt includes all canonical hard constraints, soft constraints, and
   assumptions whether the contract came from memory or persisted `contract.json`.
2. Constraint IDs, descriptions, provenance, verification mode, and result fields remain intact.
3. Direct callbacks and command generators keep their existing `GenerationRequest` contract.

### User Story 2 — Align with the frozen scoring authority (P1)

1. In `solve --evolve --compile-evaluator`, the solver receives the frozen objective and a bounded
   evaluator-source projection identified by the verified bundle/evaluator SHA-256 values.
2. Exact objective and evaluator files are copied read-only into each isolated Agent generation
   workspace, so tool-capable local Agents may inspect the full scoring code.
3. Compiler self probes, adversarial audit probes, private input profile, raw input values, and
   source-machine paths are never copied or included in the solver prompt.

### User Story 3 — Preserve evaluator authority and recovery (P1)

1. The scoring projection can be constructed only from a bundle that passes the v2 loader and
   whose fingerprint still matches the compiled handle.
2. Candidate code cannot change the authoritative evaluator; evaluation still runs from the
   immutable parent bundle after independent candidate execution.
3. Resume reconstructs the same scoring projection from the frozen bundle without compiler or
   auditor model calls.

## Functional requirements

- **FR-4301**: Include `hard_constraints`, `soft_constraints`, and `assumptions` in persisted
  contract prompt projection without dropping existing problem, I/O, objective, or delivery fields.
- **FR-4302**: Define one bounded immutable solver-scoring contract carrying objective text,
  evaluator source, evaluator digest, and bundle fingerprint.
- **FR-4303**: Construct that contract only after `load_evaluator_bundle` verifies exact files,
  permissions, protocol, canonical evidence, and aggregate identity.
- **FR-4304**: Stage only `scoring/objective.md`, `scoring/evaluator.py`, and
  `scoring/manifest.json` inside every compiled-evaluator Agent generation workspace; make all
  three regular and read-only before Agent invocation.
- **FR-4305**: Add a prompt-safe scoring summary with full objective and bounded evaluator excerpt,
  exact relative path, byte count, SHA-256, truncation flag, and bundle fingerprint.
- **FR-4306**: Never include or stage `probes.json`, `audit.json`, `input-profile.json`, raw inputs,
  candidate outputs, compiler/auditor transcripts, credentials, or absolute paths in this
  projection.
- **FR-4307**: Keep compiled evaluator execution, bundle recovery, callback/command generators,
  non-compiled model evaluation, population/loop selection, and OpenEvolve behavior unchanged.

## Success criteria

- **SC-4301**: A persisted-contract prompt test sees every hard/soft constraint and assumption.
- **SC-4302**: A compiled-evaluator integration fixture observes the verified scoring formula before
  its first candidate and still selects/materializes the independently best output.
- **SC-4303**: Tests prove scoring workspaces/prompts omit both probe suites, private profile facts,
  raw input values, machine paths, and credentials.
- **SC-4304**: Tampered bundles fail before projection; resumed bundles reproduce the same digests
  without compiler/auditor calls.
- **SC-4305**: Focused/full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Guaranteeing that a solver cannot search for a weakness in visible evaluator code; independent
  audit, execution, and candidate-evidence checks remain the mitigation.
- Exposing private test probes, raw data samples, output bodies, or model reasoning.
- Generating domain playbooks/skills, adding new solvers, or changing population selection in this
  increment.
