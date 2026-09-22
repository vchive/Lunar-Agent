# Implementation Plan: bounded recursive worker lifecycle

1. Bound service and Store depth consistently and derive worker-tool ancestry traversal from the
   configured service limit.
2. Require a running parent for worker-tool child creation and reject a stopped child attempt that
   lost the cancellation race before its executor started.
3. Validate executor capacity for recursive configurations and clamp worker waits to the enclosing
   AgentLoop execution deadline.
4. Add provider-free three-level AgentLoop, depth, ownership, cancellation, timeout, and workspace
   isolation fixtures.
5. Run focused worker regressions, Ruff, compileall, and the existing shared regression selection;
   record results without changing frozen historical evidence.
