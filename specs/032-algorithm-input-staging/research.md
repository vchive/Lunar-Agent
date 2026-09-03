# Research: Algorithm Input Staging

The existing controller already treats run-relative artifacts as the durable handoff boundary, but
`InputSpec.path` was metadata only. Passing an absolute source path to a model would violate the
runtime isolation contract, while asking users to manually copy files into an unknown UUID
workspace is not a usable local Agent interface.

Staging at run creation solves both problems. The controller records a digest-bearing run-relative
artifact, then verifies and copies its bytes to each attempt. A model can read `data/raw/...` with
the existing local tools or a subprocess can open the same path using its task working directory.
The source path and data contents never enter the SQLite event payload.

The copy is intentionally not treated as a new artifact: the run-level `input_data` row is the
source of truth, and attempt directories are disposable execution material. Digest verification
before each runtime call catches local tampering or partial writes without adding a schema table.
