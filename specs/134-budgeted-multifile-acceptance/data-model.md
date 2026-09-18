# Data model

The registration keeps schema 1 with explicitly pinned fixed conditions. Limits are
`request_seconds=900` (absolute outer per-request ceiling), `candidate_seconds=600`,
`preparation_request_seconds=900`, `preparation_wall_seconds=1860`, `wall_seconds=2400`,
`max_requests=20`, `token_stop_threshold=160000`, `holdout_seconds=5`.
Normal/contract/candidate model admission is additionally capped at 600 seconds.

Native `evolution_requested` must retain candidate/preparation request/wall 600/900/1860 with
explicit sources. The schema2 start and schema3/schema4 failures are observations bound to the
parent, attempt and policy. Bad details downgrade or reject; they never create success authority.

Public results retain the existing primary/preparation/joint denominator and holdout rows.
Add observed transport HTTP status plus normalized request/wall diagnostics and preparation policy.
Counters and optional status/timing fields are strictly bounded; credentials, prompts and generated
text are not public fields. Missing usage remains null. Evidence inventory lists every retained
file's relative path, size and SHA-256; report creation never rewrites source evidence.
