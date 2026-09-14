# Data model

One transaction directory is keyed by SHA-256(parent ID, NUL, evolution run ID) under
`.evolved-output-publications/`. It contains numbered staged files, `journal.json`, and optionally
`rolled-back.json`. The parent directory contains a persistent advisory `.lock` file.

Journal version 1 binds parent ID, evolution run ID, owner task ID, and an ordered list of entries.
Each entry binds the existing output projection (artifact ID, path, format, fields, required, size,
SHA-256), a numbered staged path, its device/inode and whether the target existed before prepare.
Only up to 32 outputs of 256 KiB each and a bounded strict JSON journal are accepted.

The `evolved_outputs_promoted` payload remains compatible. A second deterministic
`output_publication_committed` event binds the journal digest in the same SQLite commit. Neither
event nor the journal is sufficient alone. `rolled-back.json` binds the journal digest and is
written only after newly created output links have been removed and affected directories synced.
The journal's owner must match both commit events and every newly allocated artifact. Reused
artifacts keep their existing IDs and parent-task owners. If the directory is missing, a read-only
SQLite probe still detects the acknowledgement and rejects the loss of journal evidence.

Transitions: prepared → committed (SQLite authority), or prepared → rolled back (filesystem
acknowledgement). Repeated recovery verifies the same terminal evidence. Conflicts or unknown
commit state preserve all available evidence and fail closed.
