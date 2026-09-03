# Contract: Benchmark Report

The CLI emits one JSON value with `--json`. `schema_version` is `"1"`; `contract_sha256` is the
canonical algorithm contract digest; `runs` contains one entry per requested strategy in the input
order. Each entry has `strategy`, `status`, `elapsed_ms`, `evaluated_candidates`,
`valid_candidates`, `best_score`, `workspace`, `archive`, and `error`.

`status` is one of `completed`, `stagnated`, `failed`, or `cancelled`. Errors are normalized to at
most 2,000 characters. The benchmark process exits successfully when configuration is valid and at
least one strategy completes or stagnates; a failed strategy is still represented in the report.
