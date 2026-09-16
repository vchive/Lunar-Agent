# Plan

1. Freeze the input-staging API, filesystem contract, errors, and independent namespace.
2. Replay Feature 104 admission with the complete plan and caller pins before filesystem IO.
3. Reuse the descriptor reader, DirectoryChain and PrivateTree to copy bounded input bytes into
   an exclusive private child, verify destination bytes, and clean safely on failure/interruption.
4. Add public exports and `candidate-bundle stage-inputs ADMISSION --plan PLAN --input-root ROOT
   --staging-root ROOT` before normal initialization. Serialized declarations use bounded no-follow
   reads; all pins are checked before source input bytes or destination directories are opened.
5. Test byte preservation, identity/pin replay, binary and empty inputs, source/destination failure
   cleanup, root aliases, and installed CLI behavior using local fixtures.
6. Run focused and full offline regressions, quickstart, lint, compilation and diff checks; update
   README, architecture, roadmap and handoff and commit locally without pushing.

## Decisions and alternatives

Inputs receive a separate directory so a target such as `main.py` cannot overwrite candidate
source. Mutating an existing source workspace would require a new workspace identity and recovery
transaction and is deferred. There is no new serialized staging receipt: Feature 104 admission
already binds the entire input table, while a host directory is temporary caller-owned state.

Existing descriptor primitives are shared instead of adding a second path traversal/writer layer.
Fresh byte checks remain mandatory; a cached verified object is not proof of current file bytes.

## Complexity tracking

No new dependency, database migration, network service, scheduler, candidate schema, or evaluator
change. Existing APIs and CLI outputs remain compatible. Offline fixture commands and independent
verification satisfy the repository constitution without running a real model or framework.
