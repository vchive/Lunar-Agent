# Plan

1. Freeze an independent source-bundle schema, bounds and static verification result.
2. Add strict DTOs, canonical identity, no-IO structural replay and bounded file verification.
3. Add the public Python API and CLI dispatch before configuration/Store initialization.
4. Verify parsing, caller pins, real filesystem boundaries, replacement detection and CLI behavior
   with independent tests; run an installed CLI fixture and the full regression suite.
5. Update usage, architecture, roadmap and handoff, preserving sealed historical measurements.

## Decisions and alternatives

Keep a standalone manifest instead of overloading single-file Candidate or the path-free producer
dependency digest. The bundle digest covers declared paths, sizes, hashes, entrypoint and contract,
not dependencies or environment. Canonical JSON avoids dependence on JSON whitespace or list order.
Reuse the private descriptor-based file reader; public failures retain bundle-specific codes.
Do not flatten files into one source or execute an entrypoint without a future runner contract.

## Constitution and complexity

No new dependencies, state transitions, database schemas or migrations. Existing runtime, recovery
and seed contracts stay compatible. Static checks have bounded local IO and no runtime adapter.
The new tests precede implementation and exercise rejection and side-effect boundaries. No
constitution exception is needed. 051/074/076/078/082 sealed artifacts remain unchanged.
