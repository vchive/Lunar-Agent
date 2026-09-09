# Feature 066: Budget Failure Evidence

## Goal

Future subject budget failures identify the token or configured-cost ceiling and the bounded usage
that triggered it. Feature 065's two failed attempts exposed this diagnostic gap; they remain frozen
negative results, with unknown full usage and no quality scores. This feature adds no real evaluation.

## Acceptance scenarios

1. **P1 — Explain a rejected response.** When normalized cumulative usage exceeds a profile ceiling,
   preserve the accepted ledger and capture a separate observed snapshot including the rejected
   response. Report the limit, `exceeded`, configured maximum, and `trigger_recorded=false`.
2. **P1 — Explain exhaustion.** When a tool-bearing response exactly reaches a ceiling, report
   `exhausted`, `trigger_recorded=true`, and identical accepted/observed snapshots. No tool runs.
   A final text response exactly at the ceiling still succeeds.
3. **P1 — Bound the claim.** Evidence uses typed repository-owned failures, fixed fields and enums,
   bounded integers and nulls. Missing, invalid or unavailable usage never becomes a budget fact.
   Raw provider text, exceptions, tool arguments, paths, credentials and scores are excluded.
4. **P1 — Preserve authority and history.** Both normal and deep failures may collect v2 evidence,
   but still fail without a receipt, harness call, score, or complete run usage. Strict v1 diagnostics
   remain readable and collect unchanged. Existing event counters keep their original meanings.

## Requirements and limits

- Token checking retains precedence if both ceilings are exceeded; cost remains cumulative profile
  arithmetic (per-direction rounding), not an invoice or a sum of rounded response costs.
- All budget evidence is `usage_completeness=partial`: observed normalized responses do not establish
  complete provider consumption, retries, hidden tokens or billing. No backfill of historical runs.
- Numeric projection has its own cap of 10^15; rounds retain the 10^6 diagnostic cap. Out-of-range
  maxima or entire snapshots become null, without clamping values or changing budget enforcement.
- Sidecars retain the 4096-byte cap, strict field sets, identity binding, exclusive safe publication,
  stale-file rejection and best-effort failure isolation. A structurally valid claim is not trusted
  execution evidence and cannot authorize scoring, resume or promotion.
- No changes to model prompts, tool behavior, budgets, successful receipts, reports, or experiment
  denominators. No WebAgent execution, provider call or company-platform access.
