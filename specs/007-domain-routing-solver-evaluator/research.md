# Research Notes

- WebAgent v2.5 separates Master routing, domain Solver, and independent Evaluator. Local Lunar-Agent
  keeps that effect-layer separation but maps it to Python contracts instead of OpenCode services.
- Deterministic routing is safer for a first local release: reproducible tests, no extra model call,
  and no dependency on Hermes/OpenCode discovery.
- SQLite nullable columns are the least disruptive migration for existing Feature 006 databases.
