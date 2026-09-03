# Data Model: Algorithm Input Staging

## CLI value

```text
SOURCE
SOURCE=DEST
```

`SOURCE` is an existing regular local file. `DEST` is a portable relative path below
`data/raw/`; when omitted it is the source basename.

## Ledger artifact

```json
{
  "kind": "input_data",
  "path": "data/raw/orders.csv",
  "sha256": "<64 hex characters>",
  "size": 1234
}
```

The `algorithm_input_staged` event repeats only `path`, `sha256`, and `size`. It is keyed by run and
destination so retrying the same staging request is idempotent.

## Attempt materialization

```text
<run>/data/raw/orders.csv                 authoritative, hashed copy
        │ verify size + SHA-256
        ▼
<run>/tasks/<task>/<attempt>/data/raw/orders.csv   disposable runtime copy
```

All existing components are checked for symlinks and the destination must remain below the attempt
root. No attempt copy is added to the artifact ledger.
