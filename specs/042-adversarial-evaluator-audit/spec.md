# Feature Specification: Adversarial Evaluator Audit

**Feature Branch**: `042-adversarial-evaluator-audit`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Feature 040 compiles a frozen evaluator and asks that same compiler response to provide its own
constraint and score-order probes. Feature 041 grounds the compiler in exact, private structural
facts from staged data. This prevents later judge drift and schema guessing, but the evaluator and
its self-tests still share one generation context. A logically weak evaluator can therefore produce
matching weak probes, pass preflight, and reward candidates that exploit the same omission.

This feature adds a second, fresh evaluator-auditor turn before bundle promotion. The auditor sees
the immutable contract, private structural profile, objective, and evaluator source, but not the
compiler's probes, solver candidates, search archive, raw input values, or outputs. It must construct
an alternative bounded suite that independently attacks every hard constraint and score ordering.
Both suites must pass against the same evaluator before the bundle can become scoring authority.

## User stories and acceptance scenarios

### User Story 1 — Challenge the generated judge independently (P1)

1. Given `solve --evolve --compile-evaluator`, Lunar-Agent invokes the evaluator compiler once and
   then invokes an isolated auditor once before generating any candidate.
2. The auditor receives no compiler probe content or solver evidence and returns only one strict
   probe-suite JSON object.
3. The audit suite contains exactly one rejecting probe for every hard constraint, at least two
   valid probes, and at least one strict better/worse assertion.

### User Story 2 — Fail closed on correlated evaluator mistakes (P1)

1. Compiler self-tests may pass while an independently generated counterexample exposes a missed
   constraint, false rejection, invalid report, or reversed/equal score.
2. Any malformed, unsafe, incomplete, oversized, or failing audit aborts before search and leaves
   no trusted bundle.
3. The auditor cannot modify evaluator source, objective, contract, profile, or compiler probes.

### User Story 3 — Freeze and recover the audit evidence (P1)

1. Canonical `audit.json` is read-only, artifact-indexed, and included in bundle identity.
2. Resume verifies all audit bytes and reuses the frozen result without another compiler or auditor
   model call.
3. Audit/profile/bundle tampering, symlinks, writable files, or contract/input drift fail closed.

## Functional requirements

- **FR-4201**: Run one fresh auditor invocation after compiler-envelope validation and compiler
  preflight, but before atomic bundle promotion or candidate generation. Repository-owned Agent
  Loops must execute both compiler and auditor as stateless, tool-free turns that ignore any
  configured session transcript or durable memory tools.
- **FR-4202**: The auditor prompt includes only canonical contract, private input profile and digest,
  frozen objective, and evaluator source. It must exclude compiler probes and all candidate/search
  evidence.
- **FR-4203**: Strictly parse a bounded audit suite with exact hard-constraint coverage, one invalid
  probe per constraint, at least two valid probes, and strict score-order assertions.
- **FR-4204**: Reuse the same path, content, report, validity, error-code, timeout, and score-order
  checks for compiler and auditor suites; label failures by their source.
- **FR-4205**: Persist canonical `audit.json`, include its SHA-256 in manifest and aggregate bundle
  fingerprint, freeze it read-only, and index it as an evaluator-bundle artifact.
- **FR-4206**: Use a separate auditor workspace and never expose either probe suite or generated
  evaluator source to solver generation workspaces.
- **FR-4207**: Resume performs no model call and rejects audit bytes or manifest drift before score
  execution. Existing owner harnesses, model evaluators, and non-compiled paths remain unchanged.

## Success criteria

- **SC-4201**: A deliberately weak evaluator passes its compiler probes but fails an independent
  audit counterexample before the first solver call.
- **SC-4202**: A valid evaluator completes exactly one compiler and one auditor call, selects the
  correct candidate, and resumes with zero additional calls.
- **SC-4203**: Auditor prompts contain structural profile facts but no compiler probe marker, raw
  row value, source-machine path, candidate source, or output content.
- **SC-4204**: Audit tamper, malformed response, unsafe path, missing coverage, validity mismatch,
  wrong error code, and reversed/equal score tests all fail closed.
- **SC-4205**: Focused/full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Claiming two calls to the same configured model are statistically or organizationally independent;
  callers may inject a separate auditor runtime through the library seam in a later integration.
- Fuzzing unbounded input spaces, formal verification, OS-level evaluator sandboxing, or changing a
  frozen evaluator after audit failure.
- Revealing raw user data to improve adversarial probe generation.
