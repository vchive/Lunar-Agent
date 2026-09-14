# Plan

Add a fixed-schema attestation parser and Store nonce receipt. The controller validates the supplied
receipt and exact execution inode/digest under the child lifecycle lock, then calls the existing
`publish_materialization_execution` path. The attestation event is written atomically with the 091
execution batch; replaying the same nonce is idempotent only when all bound fields match.

No runner, output promoter, terminal publisher or schema migration is added. All failed checks are
fail-closed and leave source evidence unchanged.
