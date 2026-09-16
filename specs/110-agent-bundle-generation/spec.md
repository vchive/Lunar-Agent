# Feature 110: Agent-generated multi-file candidates

## Outcome

Use the existing Agent worker/runtime to propose complete multi-file candidates for the native
bundle population pipeline. Users supply the fixed local evaluator profile and select an Agent;
they no longer need to write a command generator implementing the source-map protocol themselves.

## Acceptance

1. Explicit bundle mode in `AgentCandidateGenerator` accepts complete entrypoint/files JSON and
   returns `CandidateDraft.from_files`. Existing single-file generation and response shapes remain
   compatible. Bundle mode never silently treats the entrypoint as the entire candidate.
2. The Agent sees the contract, fixed execution/input convention, bounded verified evaluation
   feedback and all parent source files. Large source maps remain accessible in the generation
   workspace without exceeding the existing prompt ceiling. Declared inputs are verified and
   staged; local evaluator implementation and private evaluation trees are not staged for the Agent.
3. A fresh generation workspace prevents an interrupted generation from reusing stale context.
   Invalid responses, source/input drift and unsafe context fail before candidate execution or
   archive publication. Agent-reported scores do not replace the fixed independent evaluator.
4. `evolve-bundle` supports explicit command, Agent command and native runtime generation modes.
   Configuration validates before home/Store creation. Generator identity distinguishes modes
   on resume; the original command fingerprint remains compatible.
5. Real local fixture workers generate helper-only improvements through population/controller,
   independent evaluation and complete delivery. Terminal resume invokes no worker or candidate.

## Scope

The existing profile remains the evaluator authority. This feature does not generate/approve new
evaluators, route normal solve tasks automatically, integrate external bundle seed import or launch
real model/framework measurements. No new attestation flow, remote service or dependency is added.
User now authorizes normal pushes of completed and verified changes; do not accumulate local work.
