# Implementation Plan: Adversarial Evaluator Audit

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

`compile_evaluator_bundle` already parses one strict compiler envelope, builds immutable synthetic
probe workspaces, executes the generated evaluator under bounded subprocess controls, and atomically
freezes a content-addressed bundle. Feature 042 adds a second suite through the same parser and
preflight machinery rather than creating another evaluator protocol.

## Decisions

1. **Fresh turn, separate workspace** — the configured runtime is invoked again under
   `.evaluator-auditor`; compiler conversation/probes are not included in its prompt. A
   repository-owned Agent Loop uses stateless, tool-free turns for both compiler and auditor, even
   when ordinary solver sessions opt into transcript history or memory.
2. **Same proof obligations** — the independent audit must cover all hard constraints, include two
   globally valid anchors, and prove strict objective ordering.
3. **No repair loop** — audit failure rejects the bundle. The judge cannot rewrite itself in
   response to an attack because that would weaken the freeze boundary and complicate provenance.
4. **Shared execution gate** — audit probes use the exact Feature 040 source/path/report/score
   validator. Differences in validation would create an easier second protocol to exploit.
5. **Frozen evidence** — canonical `audit.json` becomes the sixth exact bundle file and its digest
   participates in `bundle_sha256`.
6. **Recovery without models** — existing bundles validate `audit.json` and manifest digests; only
   first-time compilation invokes compiler and auditor.

## Data flow

```text
contract + private profile -> compiler -> evaluator + self probes -> local preflight
             |                         (self probes withheld)
             + evaluator/objective ----------------> fresh auditor -> attack probes
                                                              |
                                               local adversarial preflight
                                                              |
                               objective/evaluator/self/audit/profile -> freeze
```

## Recovery and safety

- Auditor output is bounded strict JSON and passes existing credential/path/content rules.
- The auditor workspace is outside generation archives and is never indexed as solver evidence.
- No raw input values are introduced: the auditor sees only the Feature 041 structural profile.
- Any audit exception is reduced to a bounded category at the model-runtime boundary.
- Atomic staging cleanup removes incomplete bundles after either suite fails.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses existing repository runtime and stdlib execution. |
| Local-First and Durable State | Pass | Audit suite is local, canonical, hashed, and resumable. |
| Runtime Adapter Isolation | Pass | Audit is an injected runtime call, not model-specific code. |
| Artifact-First Verification | Pass | Executed probes, not prose claims, determine admission. |
| Bounded Autonomy | Pass | Strict suite limits, timeout, no repair loop, fail closed. |
| Test-First Recovery | Pass | Correlated-failure and resume tests precede implementation. |

## Complexity tracking

No service, database migration, tenant state, external dependency, or new CLI flag. The stronger
audit is part of the existing explicit `--compile-evaluator` authority boundary.
