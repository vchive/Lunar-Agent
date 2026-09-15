1. Extend the strict arm DTO with an optional path/size descriptor while preserving Feature 099 JSON.
2. Verify confined regular-file bytes under an explicit evidence root.
3. Expose the check through the static comparison validation CLI and public Python API.
4. Add failure-first coverage for valid files, changed bytes, symlinks and unsafe paths.

Follow-up: replace path-based reads with descriptor-relative reads and final name checks. Reuse the
same private reader for result JSON and evidence, keeping file errors mapped to their existing fixed
codes. Retain the public APIs, CLI flag and schema. Add deterministic file substitution and malformed
input regressions before implementation. No dependencies, Store changes or execution are needed.
