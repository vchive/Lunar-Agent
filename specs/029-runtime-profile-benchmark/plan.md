# Implementation Plan: Runtime Profile Benchmark

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Extend the benchmark CLI's explicit command pair into an explicit runtime profile. Reuse
`_build_evolution_runtime`, `RuntimeAgentAdapter`, `AgentCandidateGenerator`, and
`AgentCandidateEvaluator` so runtime-backed benchmark calls remain identical to `evolve` calls.
Extend `BenchmarkConfig` with a credential-safe runtime profile snapshot; no database migration is
needed.

## Decisions

1. **One profile per invocation** — compare one-shot and loop by running the same command twice with
   separate workspaces; this keeps report entries unambiguous and avoids a new matrix model.
2. **No mixed OpenEvolve** — native runtime profiles and external OpenEvolve have different process
   budgets; compare them through separate benchmark invocations for now.
3. **Same adapters** — runtime-backed generation/evaluation use the existing strict bridge classes,
   not benchmark-specific parsing.
4. **Explicit secrets** — API key resolves from the benchmark flag or
   `FAMOU_AGENT_RUNTIME_API_KEY`, and only its redacted runtime behavior is tested.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Repository runtime and standard library only. |
| Local-First and Durable State | Pass | Fresh local workspace per strategy/profile. |
| Runtime Adapter Isolation | Pass | Existing adapter bridge remains the only model seam. |
| Artifact-First Verification | Pass | Strict candidate/evaluator validation remains authoritative. |
| Bounded Autonomy | Pass | Existing loop, tool, timeout, and path guards are reused. |
| Test-First Recovery | Pass | Fake endpoint and option safety tests precede completion. |

## Complexity tracking

No new dependency, service, or store table is introduced. The benchmark report gains only a
JSON-safe runtime profile descriptor and fingerprint.
