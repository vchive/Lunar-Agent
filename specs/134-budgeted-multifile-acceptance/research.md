# Research decisions

The read-only design review compared Features 113, 128, 131 and 133 before implementation.

1. Feature 131 reused one `request_seconds=600` for the outer guard and candidate `--timeout`.
   A higher native preparation value would still be clipped at 600 without separating these.
   Keep controller environment and candidate limits 600, use outer request cap 900 and explicitly
   pass preparation request/wall 900/1860. Offline full-worker tests must observe this routing.
2. A larger 1200/2460 preparation policy with 3600 campaign seconds was considered. Choose
   900/1860 with the unchanged 2400 campaign ceiling to test independent preparation policy while
   preserving the old overall limit. Worst-case early work can exhaust time before candidate
   delivery; the ceiling is a bound, not a promise of time for every later stage.
3. The frozen shared request guard records native failures but replaces their exception type.
   Preserve typed failures only in the new observer after confirmed durable failure accounting;
   never replace journal/admission errors or admit another request. Keep frozen 113 unchanged.
4. Feature 131 retains HTTP status in private transport metadata but omits it from public results.
   Project only bounded single-exchange status tied to the exact request; missing status stays null.
5. Native schema3/4 observation readers already validate attempt binding and safe diagnostic shapes.
   Reuse them and validate native policy against registration. Persisted parent `running` together
   with effective `failed` is intentional recovery behavior, not a defect to rewrite.
6. Reuse the eight holdouts and exact task without replaying old source. The successful Feature128
   preparation is context, not permission to skip a new compiler/auditor or to count this as causal.
7. Independent preregistration review found that using only the current Git index could omit a
   deleted product file. Compare the complete tracked set to the fixed product commit in both
   registration and verification. Validate provider identity before consuming a slot, then recheck
   in the worker; read-only verification and summarization must remain credential-independent.
