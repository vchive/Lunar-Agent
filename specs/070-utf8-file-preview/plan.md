# Plan: UTF-8 File Preview Boundaries

1. Reproduce the artificial UTF-8 cutoff failure with temporary files before implementation.
2. Use the standard-library strict incremental UTF-8 decoder. Set `final=False` only when the
   actual file was truncated; otherwise preserve strict EOF validation.
3. Preserve the existing marker, output-byte interpretation and ToolResult shape. Clarify the
   existing model-visible parameter description to describe a complete-character prefix.
4. Verify all multibyte cutoffs, real invalid data, true EOF, ASCII and exact-limit behavior;
   run adjacent tool/runtime tests and independent review in the isolated worktree.
5. Commit the reviewed change on `codex/read-file-utf8-prefix`. Leave the active main checkout
   and its frozen source/tests untouched. Integrate only after Feature 069 termination and audit.

## Decisions and alternatives

The incremental decoder distinguishes incomplete trailing input from malformed visible bytes
using Python's existing UTF-8 implementation. `errors="ignore"` or `errors="replace"` would hide
real invalid bytes and is rejected. Manually searching backward for byte boundaries is unnecessary.
The file is still read once through the existing path guard; no file-format or state migration is
needed. The only new import is from the Python standard library.

## Contracts and data model

There are no new arguments, result fields, artifacts or persisted records. `read_file(path)` remains
a bounded UTF-8 preview. Its text content may contain fewer than `max_output_bytes` encoded bytes
when the omitted next code point spans the cutoff. The original truncation marker remains the
only indication that further bytes exist. No private evaluator or workflow authority changes.

## Runnable verification

Inside the isolated worktree, using the existing repository environment:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest \
  -o addopts='' -q tests/test_tool_utf8_preview.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou/tools.py tests/test_tool_utf8_preview.py
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

Confirm `famou.tools.__file__` points into this worktree before testing. Run the adjacent tests and
full suite with the same explicit source selection. Use no API credentials or actual model calls.

## Constitution review

No exception: small standard-library change, no additional runtime dependency or service, no
state/receipt migration, independent fixture verification and unchanged execution authority.
The active measurement checkout is isolated from this implementation until its evidence closes.
