# Feature Specification: bounded recursive worker lifecycle

**Created**: 2026-09-22
**Status**: Implemented locally; provider-free validation in `validation.md`

## Problem

Feature 143 exposes worker tools to a running AgentLoop, but its acceptance covered only one
parent-to-child hop. A child must be able to create and observe a grandchild without weakening
owner checks, cancellation boundaries, result privacy, or the bounded execution contract.

## Scope

This extension enables a configured recursive worker depth up to 32 for the local WorkerService.
It covers AgentLoop worker-tool calls, direct lifecycle cancellation, bounded waits, and durable
result isolation. The default service depth remains one. Automatic solve, candidate generation,
remote providers, and external producer scheduling remain separate integrations.

## Contract

- A service configured with `max_depth=N` permits worker depths `0..N`; the protocol maximum is 32.
- Recursive configurations with `N > 1` require at least `N + 1` executor slots, providing capacity
  for one isolated chain of parents synchronously waiting for descendants. Arbitrary branching
  and concurrent roots require additional capacity; this lower bound does not guarantee them.
- A worker-tool spawn requires its current parent to still be running. The parent check and child
  record creation are performed under Store write serialization; a cancellation race leaves a
  terminal child record and cannot start a new attempt under a cancelled parent.
- Cancellation also settles idle children that have no first attempt yet. Explicit child resume
  rejects a cancelled or parent-cancelled parent in the same Store admission transaction, while
  remaining available after a successfully completed parent.
- A worker may read, wait for, or cancel only its owned descendant subtree. Siblings, ancestors,
  and other owners are rejected without Store or runtime side effects.
- `wait_worker` timeout is an observation result. It returns a bounded running projection and does
  not settle or cancel the child. A later wait can observe the final result.
- Ancestor cancellation reaches every owned descendant. The root receives `cancelled`; descendants
  receive `parent_cancelled`. A late adapter result cannot replace those terminal outcomes.
- Each attempt keeps its own workspace and result envelope. Reading a descendant result returns
  bounded text and metadata; descendant artifacts are not copied into an ancestor workspace.
- An AgentLoop execution deadline also bounds a worker-tool wait. The existing continuation guard
  remains authoritative between short polls.

## Non-goals

No live interruption of `send`, automatic retry, shared mutable adapter instances, remote worker
transport, or automatic solve integration is added here.
