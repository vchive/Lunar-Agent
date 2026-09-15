1. Extend the strict arm DTO with an optional path/size descriptor while preserving Feature 099 JSON.
2. Verify confined regular-file bytes under an explicit evidence root.
3. Expose the check through the static comparison validation CLI and public Python API.
4. Add failure-first coverage for valid files, changed bytes, symlinks and unsafe paths.
