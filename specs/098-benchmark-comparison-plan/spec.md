# Feature 098: Fixed-condition benchmark comparison plan

**Created**: 2026-09-14
**Status**: Complete

## Problem

A shared task envelope identifies one workload, but a multi-framework comparison still needs an
immutable plan that prevents arms from silently changing task, model, evaluator or physical budget.

## Requirements

- FR-098-01: Define `lunar-benchmark-comparison-v1` with at least two uniquely identified arms,
  each carrying a 097 task envelope and common contract/model/evaluator/budget bindings.
- FR-098-02: Require every arm to share the same 097 comparison digest and derive a comparison ID
  from workload and common conditions, excluding framework names, scores and run IDs.
- FR-098-03: Provide strict canonical parsing and read-only admission that rechecks each arm's input
  bytes and caller pins without invoking a framework, model, evaluator, scheduler or Store.
- FR-098-04: Preserve per-arm physical budget isolation; derive total attempts only as arms times
  per-arm attempts. Do not alter existing BenchmarkRunner strategy semantics.

## Limits

This feature freezes comparison conditions only. It does not run SkyDiscover, LLM4AD, Lunar or any
other benchmark, and produces no effectiveness or parity claim. Repository/workflow, training/RL and
remote candidates remain outside this plan.
