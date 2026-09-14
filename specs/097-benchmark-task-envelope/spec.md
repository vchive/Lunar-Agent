# Feature 097: Benchmark task envelope

**Created**: 2026-09-14
**Status**: Complete

## Problem

SkyDiscover and LLM4AD style benchmark runners use different task metadata. Lunar needs one
bounded, content-addressed task envelope so a future comparison can bind the same contract, input
bytes, evaluator, model profile and physical budget without importing either framework.

## Requirements

- FR-097-01: Define schema `lunar-benchmark-task-v1` with benchmark/task identity, contract digest,
  input descriptors, model/evaluator pins, candidate kind and physical budget.
- FR-097-02: Parse canonical JSON with strict fields, bounded values, safe relative paths, no
  duplicate keys/nonfinite numbers/secrets/private harness paths, and stable envelope/comparison digests.
- FR-097-03: Admit an envelope only after rechecking the contract, input bytes, model profile and
  evaluator pins supplied by the caller. Admission is read-only and never runs a producer, model,
  evaluator or scheduler.
- FR-097-04: Add `benchmark-task validate` CLI before normal configuration initialization. It emits
  only bounded identity/digest data and fixed errors; it must not create Lunar home or Store.
- FR-097-05: Provide offline SkyDiscover/LLM4AD mapping fixtures and document that external scores,
  generation IDs and framework metadata never become Lunar score, rank or iteration authority.

## Limits

This feature does not invoke SkyDiscover, LLM4AD, OpenEvolve, ShinkaEvolve, models, providers,
remote services or campaigns. It accepts single-file benchmark tasks and digest-only input
references. Multi-file repository/workflow, training/RL and remote lifecycle envelopes are separate.
