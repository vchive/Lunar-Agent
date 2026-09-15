# Data model

`CandidateWorkspacePlan` is a frozen, path-free DTO containing protocol/schema, contract and bundle
digests, entrypoint, command tuple, sorted environment pairs, timeout/output limits, file count,
total bytes, file-table digest, and `workspace_cwd='.'`.

`VerifiedCandidateWorkspace` contains the allocated workspace path plus the same bundle/contract and
file-table metadata. Its identity never includes the local absolute path.

`CandidateWorkspaceError` exposes only fixed `candidate_workspace_*` codes.
