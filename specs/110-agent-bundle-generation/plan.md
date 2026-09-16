# Plan

1. Reuse AgentCandidateGenerator and existing AgentAdapter/RuntimeAgentAdapter protocols with an
   explicit bundle pipeline option. Keep single-file behavior unchanged.
2. Prepare a fresh generation context with verified inputs, complete parent source files and
   bounded report summaries. Reuse the existing prompt limit and experiment metadata conventions.
3. Parse only complete bundle responses in bundle mode, reusing CandidateDraft/Feature 102 limits.
4. Extend `evolve-bundle` selection and fingerprinting, retaining its fixed local evaluator profile.
5. Exercise real local Agent commands and fixture runtimes, candidate scoring, helper improvement,
   delivery, resume, malformed context/response cases and old Agent/CLI regressions.
6. Publish a runnable quickstart, update readiness/handoff, run full checks, commit and push.

No private evaluator implementation is copied into generation context. Runtime support is explicit
configuration; validation uses local fixtures, not remote model calls. Broader normal-task routing,
parent-run delivery/recovery and current-version effectiveness remain separate milestones.
