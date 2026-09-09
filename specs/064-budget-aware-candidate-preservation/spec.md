# Feature Specification: Budget-Aware Candidate Preservation

**Branch**: `main`
**Created**: 2026-09-09
**Status**: Complete

## Problem and scope

WebAgent's runtime-budget guidance motivates preserving a complete candidate before expensive
refinement. Lunar already enforces profile budgets after responses, but profiled commands receive
the fixed registry timeout rather than the invocation's remaining time, and `write_file` truncates
the destination before completing a replacement. These are locally verifiable limitations; neither
is established as the cause of the frozen GLM failures.

This feature implements the smallest usable slice: transient budget guidance for profiled normal
tool loops, cooperative command timeout propagation, and atomic replacement through the existing
write tool. It does not introduce a checkpoint authority or automatic continuation protocol.

## Requirements

1. Before each model request in `AgentLoopRuntime.run` with a profile, present one current numeric
   budget snapshot: remaining wall time, tool steps, cumulative token/cost allowance where configured,
   and the currently possible single-command timeout (null when execution is disabled). Derive time
   from the same invocation clock and spend from its existing accepted usage ledger. Missing ceilings
   remain null; do not invent prices, complete failure usage, or available reasoning tokens.
2. Snapshot prose explains that current and future calls still consume those allowances. Recommend
   saving a complete candidate before refinement, giving scripts an internal deadline shorter than
   the actual command window, and atomic incremental output. Guidance is advisory, not a promise of
   an incumbent or a new success criterion. Never encourage empty/partial output to masquerade as valid.
3. The snapshot is regenerated in the outgoing system context only. It must not accumulate in the
   message history, transcript or memory, mutate caller messages, enter isolated protocol calls, or
   expose credentials/paths/provider bodies. Preserve message roles and tool call/result pairing.
4. For profiled tool execution, propagate the invocation's absolute monotonic deadline through a
   context-local scope. Immediately before launch, command timeout is the smaller of configured
   timeout and remaining invocation time. No command launches after expiry. Do not mutate the registry
   timeout or relax nested deadlines; restore the scope on all exits. Keep the existing three-argument
   execute signature, so existing subclasses/fixtures continue to work.
5. Preserve partial command output on timeout whether stdout/stderr are bytes, text, empty or absent.
   A command timeout remains a failed tool result. Preserve existing whole-invocation failure checks;
   no final response, receipt or later action may bypass the profile deadline or spend ceiling.
6. `write_file` atomically publishes each complete UTF-8 replacement through a unique same-directory
   temporary file. On handled pre-publication failure, preserve the previous destination and remove
   temporary files when cleanup succeeds; artifacts are reported only after publication succeeds.
   Preserve an existing file's permission bits (including executable); new files are private 0600.
   Keep workspace confinement and current content limits. Atomic replacement changes the inode, so
   other hard links still refer to the previous content. Do not create a new scoring/checkpoint schema.
7. Existing no-profile loop context/timing, isolated messages, model profile schema and receipt,
   evaluator, promotion and resume authority remain unchanged. Atomic writes and timeout-output
   normalization apply to the common local tools. Failed attempts may retain files but remain failures.

## Acceptance

- Fake-clock multi-turn tests show shrinking time/steps/spend and fresh invocation reset, no stale
  snapshot in transcript, no hint in isolated/no-profile calls, and unchanged tool pairing.
- Commands receive the smaller limit, sequential commands recompute remaining time, expired commands
  never spawn, and exceptions/nesting/concurrent contexts cannot leak a deadline into another call.
- A real bounded child that emits only stdout or only stderr returns its partial output on timeout
  without a bytes/string TypeError. No background execution or SIGTERM grace is promised.
- Interruption before atomic publication preserves the old file; after publication the complete new
  file is visible. Unsafe paths fail and no unsuccessful write reports an artifact.
- A subject that writes a candidate then exhausts its profile retains that file without a successful
  receipt, harness invocation or new score. The fixed 2026-09-09 campaign stays untouched.

## Limitations

Timeout propagation is cooperative. Process startup, cancellation, filesystem I/O and uncooperative
descendants may outlast a requested timeout. This feature does not add streaming, process-tree
cancellation, power-loss durability, automatic salvage/resume, or run scripts on behalf of the model.
Forced process death or cleanup failure can leave an unregistered temporary file. This is per-file
atomic publication, not a multi-file transaction or a guarantee to recover incomplete work. The existing
tool output truncator still uses a character count; this feature only normalizes timeout stream types.
Model-visible changes require a separately frozen future campaign; no effect claim follows from tests.
