# Feature 100: Benchmark comparison evidence binding

Feature 099 receipts identify each arm's evidence by SHA-256 only. Feature 100 adds an optional
bounded file descriptor and a read-only admission path that verifies the descriptor against bytes
under an operator-supplied evidence root.

## Requirements

- `ComparisonArmResult` MAY contain `evidence_path` and `evidence_size` together. Existing digest-only
  receipts remain valid when no evidence root is supplied.
- A descriptor path is a normalized relative POSIX path. Absolute paths, `..`, empty components,
  NULs, backslashes, symlinks and non-regular files are rejected.
- When `evidence_root` is supplied, every planned arm MUST provide a descriptor. The root and every
  ancestor MUST be non-symlink directories, and file size and SHA-256 MUST match the receipt.
- Descriptor fields participate in the derived `result_id`; changing the path or size changes result
  identity even when the content digest is unchanged.
- Validation is bounded and read-only. It never starts a framework, model, evaluator, provider,
  scheduler, Store or remote service.

The descriptor binds a receipt to observed local bytes. It does not certify who produced those bytes,
prove framework correctness, or import scores into Lunar candidate or iteration authority.
