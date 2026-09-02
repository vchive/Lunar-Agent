# Quickstart

```bash
famou run "analyze this CSV and write a report" --runtime mock --json --home .lunar
famou status <run-id> --json --home .lunar
```

The status object includes `route` and `budget` metadata. A custom evaluator can still be injected
from Python using `LocalController(..., evaluator=...)`; no Hermes installation is read.

## Validation record

2026-09-02: Python 3.13 full suite passed (59 tests), Ruff passed, Python 3.11 bytecode compilation
passed, and the mock CLI quickstart returned a succeeded `data` route. Python 3.12 was unavailable
on the development machine.
