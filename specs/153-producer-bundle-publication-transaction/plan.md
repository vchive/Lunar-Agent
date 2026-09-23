# Implementation plan

1. Define bounded journal, candidate receipt, and terminal-state DTOs with strict canonical JSON
   parsing and a journal digest.
2. Derive deterministic candidate identities from the Feature 152 plan without changing the
   existing `CandidateDraft` identity rules.
3. Add a read-only preflight that compares plan, archive-prefix, workspace, and authority pins
   before opening a publication transaction.
4. Implement a private staging tree and one recovery marker for all candidate source trees,
   sidecars, archive lines, and state updates; publish only after every receipt is verified.
5. Add fail-closed resume and unknown-publication handling. Keep the legacy seed publisher and
   automatic solve entry points untouched.
6. Add focused provider-free transaction, tamper, crash-boundary, and no-provider tests, then run
   the normal static and regression gates.
