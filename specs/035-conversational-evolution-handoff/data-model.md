# Data Model: Conversational Evolution Handoff

No SQLite schema migration is required.

## Link event

The intake run records one deterministic `evolution_linked` event:

```json
{
  "evolution_run_id": "…",
  "contract_sha256": "64 lowercase hex characters",
  "strategy": "loop|population|openevolve"
}
```

The event ID is derived from the evolution run ID and contract digest, so a retry cannot create a
second relationship. The child run has its own `evolution_configured`, strategy lifecycle, and
artifact rows.

## Copied input artifacts

Input rows in the child use the existing `kind=input_data` shape and paths below `data/raw/`.
Their `sha256` and `size` must match the source row. The source machine path is not represented in
the ledger or event payload.
