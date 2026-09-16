# Plan

1. Extend the current frozen evaluator compiler with explicit candidate/snapshot invocation,
   retaining its envelope, independent audit and probe/freeze lifecycle.
2. Prepare/recover an ordinary bundle pipeline from the parent's exact ledger, frozen snapshot
   evaluator and bounded local defaults. Pin and index preparation using current Store facilities.
3. Add conversational `--multi-file` routing and automatic continuation through the existing 111
   pipeline, with early mode and retained-evidence validation.
4. Exercise generation, independent scoring, parent delivery, clarification, interruption, drift,
   budgets and legacy compatibility with local fixtures. Provide a standalone subprocess example.
5. Freeze implementation, run the full suite and repository checks, document limits, commit/push.

No wrapper fabricates old candidate/execution files. Snapshot evaluators use the existing 108
request/report formats directly; explicit profiles and single-file evaluator bundles retain their
current defaults and identities.
