# Plan

1. Reproduce same-name arm provenance substitution and invalid in-memory plan acceptance.
2. Add structural plan replay, optional result pin and explicit receipt factory; preserve legacy IDs.
3. Extract the existing 100 file reader into a private shared benchmark module; use it for task/plan
   parsing and input admission too. Keep failure codes owned by each public API.
4. Add caller pin CLI wiring and separate plan/evidence binding flags in output.
5. Verify API and CLI, source-byte preservation, malformed input and replacement cases; run full
   regression and record final evidence. Keep 051/074/076/078/082 frozen files untouched.

An optional v1 field avoids migrating legacy receipts. A new protocol or automatic pin insertion
would either break existing data or imply unsupported provenance. Multi-file candidates and live
execution remain separate future designs. No new dependency or persistence schema is needed.
