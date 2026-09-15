# Validation

Feature 103 validation completed on 2026-09-15.

- Focused workspace, plan, bundle, filesystem, and CLI regression: `266 passed, 1 skipped`.
- Workspace-only regression: `107 passed, 1 skipped`.
- Ruff: `.venv/bin/ruff check src tests` passed.
- Compilation: `.venv/bin/python -m compileall -q src` passed.
- Installed CLI fixture: materialization returned a path-free metadata payload and created one
  private `0700` workspace containing only declared `0600` files. The declared entrypoint marker
  was not created and the supplied home path remained absent.
- Full pytest regression: `4276 passed, 1 skipped` in 215.87s.

The tests cover source and destination link boundaries, replacement and cleanup, static DTO replay,
no-execution markers, and no Store/home side effects. Materialization remains a bounded byte-copy
boundary; it does not execute, import, evaluate, admit, archive, or register candidates.
