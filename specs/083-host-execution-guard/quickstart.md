# Quickstart

The normal/deep trial CLI accepts `--keep-awake-report /absolute/new-host-session.jsonl` on macOS.
The report must be fresh, outside `--workspace` and all `--case-source` roots, and have an existing
parent directory with no symlink components. It requests a transient idle-system-sleep
assertion for the existing trial call and records an independent host journal. Without the option,
the existing path and native payload are unchanged. This option does not prevent manual/lid sleep.

Future fixed campaign code can use the same scope before dispatch:

```python
from famou.host_session import host_execution

with host_execution(report_path):
    result = existing_operation()
```

Keep the supervisor alive until its protected work has completed. A closed host journal is not a
native result receipt. Use a fresh observation path on each invocation, including resume.
On macOS, `/tmp` and `/var` commonly contain symlink components: use their physical paths
(`/private/tmp`, `/private/var`) or another real directory for the report.
Existing directories are checked by filesystem identity, including case/Unicode aliases. For
directories not created yet, containment is conservatively case/normalization insensitive; use a
distinct report directory if similarly named future directories are rejected.

Offline checks (no real effect trial):

```sh
.venv/bin/python -m pytest -q tests/test_host_awake.py tests/test_host_session.py tests/test_host_execution_cli.py
.venv/bin/ruff check src/famou/host_awake.py src/famou/host_session.py src/famou/cli.py tests/test_host_awake.py tests/test_host_session.py tests/test_host_execution_cli.py
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
```

Bounded local macOS checks (no model, harness, network or actual sleep):

```sh
.venv/bin/python specs/083-host-execution-guard/validation/native-smoke.py --output NEW_NATIVE_RESULT.json
.venv/bin/python specs/083-host-execution-guard/validation/native-scope-smoke.py --output-directory NEW_SCOPE_DIRECTORY
```

Both destinations must be new. The first checks native acquire/query/release and local
`os._exit(0)` cleanup; the second exercises the public scope with normal return and a fixed
exception, keeping the original JSONL clock observations. Saved results are in `validation/`.
These are local lifecycle checks, not an actual sleep test or evidence of improved valid solutions.
