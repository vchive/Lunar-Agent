# Feature Specification: Explicit Tool Parameter Contracts

**Branch**: `main`

**Created**: 2026-09-09

**Status**: Complete

## Problem

WebAgent v2.5 recently audited a provider integration where tool parameter descriptions were
silently dropped before the final model request. Lunar already emits ordinary JSON Schema, but its
parameter properties currently communicate only machine types. This makes the model infer path,
command, and memory scope rules from prose, especially when a provider renders only the parameter
schema. The contract should carry the bounded usage rules at the same boundary that carries types.

## Requirements

1. Every built-in Lunar tool parameter exposed by `LocalToolRegistry.schemas()` MUST include a
   non-empty concise `description` alongside its type/schema constraints (at most 512 UTF-8 bytes
   in the supported registry configurations exercised by the contract tests).
2. Descriptions MUST state the safety-relevant semantics that are already enforced: paths confined
   to the workspace, UTF-8 content, no-shell argv execution, bounded commands, explicit memory
   scopes, and bounded input options. They MUST NOT add permissions or behavior that execution does
   not provide.
3. The OpenAI-compatible runtime MUST forward these parameter descriptions unchanged as part of the
   final `tools` request. No provider-specific schema conversion or second description registry is
   introduced.
4. The contract remains credential-free, bounded, and backward compatible for callers that inspect
   tool names or execute existing arguments. Descriptions are documentation, not a new validation
   path.
5. Memory-only tools and the opt-in command tool MUST retain their existing visibility gates.

## Acceptance

- The schema for every enabled built-in tool has a description for every declared property, and
  descriptions are bounded UTF-8 strings.
- A captured OpenAI-compatible request contains the same parameter descriptions produced by the
  registry, including for opt-in command and memory tools.
- The descriptions accurately describe no-shell execution and memory scope restrictions; tests do
  not merely assert that a key exists.
- Existing focused/full tests, lint, compile, build, Specify checks, and diff checks pass.

## Scope exclusions

No change to tool permissions, path policy, output limits, remote memory service, provider payload
format, model selection, evaluation budget, or existing campaign artifacts. Runtime soft deadlines,
profiling, and incremental solver checkpoints are reserved for a separate experiment variant.
