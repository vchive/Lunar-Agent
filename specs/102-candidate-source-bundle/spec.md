# Feature 102: Candidate source bundle

## Problem and scope

The existing Candidate, SeedManifest and ProducerResultEnvelope accept single source files.
Repository-oriented producers need a stable identity for several declared source files before
Lunar can design their execution and evaluation. This feature adds a standalone, read-only source
bundle contract and static CLI. It does not change existing candidate or seed admission.

## P1 acceptance scenarios

1. A manifest declares a contract digest, an entrypoint and two UTF-8 source files. Verification
   checks each file's size and SHA-256 and returns the canonical bundle digest and byte counts.
   Reordering declarations leaves the digest unchanged; changing any declared field changes it.
2. A caller supplies an expected bundle digest. Contract or bundle pin mismatch fails before
   source IO. Typed objects are deeply reconstructed and revalidated before IO.
3. Missing files, links in any path component, non-regular files, byte drift and observed file or
   ancestor replacement fail with fixed error codes. Reads are bounded before allocation.
4. `candidate-bundle validate` succeeds without initializing home/Store, evaluating, importing or
   executing source. Malformed input also leaves all source material and local state untouched.

## Frozen contract

Schema `1`, protocol `lunar-candidate-source-bundle-v1`; exact fields are `schema_version`,
`protocol`, `contract_sha256`, `entrypoint`, and `files`. Each file has exactly `path`, `size`, and
`sha256`. Digests are 64 lowercase hexadecimal characters. JSON duplicate keys, unknown fields,
non-finite values, invalid Unicode and non-integer or boolean sizes are rejected.

The manifest is at most 128 KiB, declares 1–64 files, each 0–1 MiB and at most 16 MiB total.
Entrypoint exactly names a declared file. Source bytes must be UTF-8 without NUL. Empty files are
valid. No extension, syntax or language inference is performed. Files sort by Unicode codepoint
path order for canonical JSON; canonical UTF-8 JSON uses sorted keys and compact separators.

Paths are NFC, canonical relative POSIX paths, at most 1024 UTF-8 bytes. Reject empty paths,
absolute paths, empty/dot/parent components, backslashes, Unicode Cc/Cf/Cs characters and colons.
Any case spelling of a `.git` component is reserved and rejected. Reject
duplicate paths, case-folded component aliases and file/directory prefix conflicts. This is a
conservative naming contract, not a promise of portability to every filesystem. Absolute local
input paths also obey the shared 4096-byte/128-component no-symlink reader boundary.

## Limits of the result

Only declared files belong to the bundle identity. Unlisted files are not scanned, admitted or
excluded from a later process environment by this verifier. The digest is not a repository
snapshot, a dependency/environment attestation, a producer identity, an execution result or an
evaluation score. Observations are per file, not a multi-file atomic snapshot. No persistence,
copy/export, runner, import resolver, Candidate conversion, campaign or network integration is added.
