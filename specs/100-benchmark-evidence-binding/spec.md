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

## Follow-up: bounded reads and file replacement (2026-09-15)

The initial path checks leave a gap between checking a path and opening it. Repair the existing
Feature 100 contract without adding a schema or runner:

- Open directories and files relative to held descriptors with `O_NOFOLLOW`; use nonblocking
  file opens so a FIFO substituted during validation cannot hang the command.
- Bound result JSON reads to 128 KiB plus one byte and evidence reads to the declared size plus
  one byte (at most 16 MiB plus one). Reject oversized metadata before reading content.
- Check file device/inode/size/mtime/ctime before and after the read, and verify the file and
  directory names still refer to the opened objects. Reject observed replacement or mutation.
- Require descriptor keys together and non-null when present, a nonempty normalized file path,
  and an explicit root for the binding API. Reject malformed JSON and scalar values with fixed
  `BenchmarkResultError` codes, including unhashable status and overflowing numeric values.
- Keep valid legacy digest-only receipt bytes and identities unchanged. Reading may update atime;
  this is a bounded observation, not an atomic snapshot of all arms or a guarantee against writes
  after verification. Root and ancestor symlinks remain rejected, including platform aliases.
- Apply the same file-path boundary to result JSON: no `..` or ancestor links, at most 4096 UTF-8
  bytes and 128 absolute components. This intentionally tightens accepted filesystem paths, without
  changing valid receipt data or identities. Evidence descriptor paths retain their 1024-byte limit.
