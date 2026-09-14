# Validation — 2026-09-14

## Results

- First feature-focused run: 169 passed in 11.77s (75 integration, 78 Store, 16 diagnostics).
- First full regression: 3768 passed in 226.55s.
- Final review then added 20 Store cases for unrelated audit rows with absent/invalid nonce;
  combined 095/091/092 Store checks: 339 passed in 2.59s. The final feature contains 189 cases
  (75 integration, 98 Store, 16 diagnostics); these counts overlap the full regression.
- Final full regression after this nonce fix: **3788 passed in 224.61s**.
- Ruff, compileall, Specify prerequisites with required tasks, and diff check: passed.
- All 601 tracked files in Feature 051/074/076/078/082 match pre-feature commit `027a235`.
- Independent Store, CLI/recovery and diagnostic reviews completed with reported issues addressed.

## Behaviors exercised

- Canonical receipt shape, byte bound, safe identifiers, duplicate keys, nonfinite JSON, regular
  no-follow file checks, symlink/FIFO/directory rejection and fixed errors without retained secrets.
- Exact parent/child/task, full launch digest, candidate, attempt, execution digest/size/device/inode
  checks; missing or temporary execution, source drift and inode replacement during registration.
- One atomically prepared attestation per child, globally unique nonce, exact idempotent replay,
  conflicting reuse, malformed/duplicate/reserved event identities and transaction rollback.
- Fresh attestation is refused when any 088/089/092 filesystem or database downstream evidence
  exists, including completed execution with only retained downstream database rows. Invalid CLI
  preflight never opens a live writable Store and never creates a missing home.
- Same receipt is frozen across private-snapshot preflight, live registration and returned digest;
  replacing the operator file between phases cannot register one receipt and report another.
- Explicit retry after full attested journal but before DB preparation, and after preparation,
  commit or before completion; automatic recovery cannot create missing preparation. Prepared
  recovery uses the journal receipt even if the original operator file is gone.
- Removing or modifying the attestation or its prepared/journal association stops recovery;
  direct 092 Store authority also rejects missing audit evidence.
- Real subprocess CLI contention returns promptly without consuming the nonce or running a
  candidate. Subsequent valid registration succeeds.
- Succeeded and failed local candidate fixtures proceed from attestation through normal 092
  delivery, output publication and terminal replay, while runner calls are explicitly forbidden.
  The attestation command itself also forbids output promotion.
- Diagnostics recognize the new journal/event relationships, including prepared receipt digest
  drift; reports and bundles exclude nonce and receipt body and retain `not_assessed` eligibility.

## Scope and retained limits

All executions were offline fixture programs and local tests. No real model, provider, WebAgent,
OpenEvolve/ShinkaEvolve service, remote campaign or algorithm effectiveness measurement ran. This
feature makes execution registration recoverable with explicit local authorization; it adds no
external operator authentication or proof that a process ran and no exactly-once/delivery guarantee.
Partial or unattested execution journals and missing candidate/execution/output bytes still need
separate diagnosis. Unknown live processes are not detected or terminated, and evidence has no GC.
