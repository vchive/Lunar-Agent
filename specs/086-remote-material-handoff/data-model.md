# Remote material handoff data model

`RemoteExperimentState` remains the accepted observation from the transport-free lifecycle. The
bridge accepts it only after `reconcile_remote_state` has established a legal transition from an
optional earlier observation. Import requires `status=completed`, a non-null experiment ID, and a
non-empty immutable material list. Completion describes only the remote lifecycle.

`RemoteMaterialReference` remains score-free and contains exactly `kind`, POSIX-relative `path`,
`size`, and `sha256`. Feature 086 accepts only `kind=candidate_source`. The path names a file that
has already been synchronized below a local material root; the bridge does not download it. The
generic producer boundary opens the file without following symlinks, checks that it is a bounded
regular UTF-8 source, and verifies size and digest before the evaluator runs.

The bridge creates an in-memory `ProducerResultEnvelope` with protocol
`lunar-producer-result-v1`. Producer identity comes from caller pins and must match the remote
state. The current lifecycle DTO does not carry the submit request's contract digest; the caller
therefore owns that binding, while the bridge validates the supplied digest and binds it to the
local contract re-evaluation. The caller also supplies the bounded numeric budget that governed
the remote producer. Material references map one-to-one to `ProducerMaterial`; the remote
reference schema currently has no parent-lineage field, so imported materials use an empty
bounded lineage tuple. Remote IDs and lifecycle observations enter only normalized external
evidence. If an experiment ID is outside the generic producer identifier alphabet, the persisted
producer-run label is a deterministic SHA-256 based opaque identifier, while the digest-only state
evidence still binds the complete remote identity.

`admit_producer_envelope` is the object-level form of the existing file-envelope adapter. Both
forms perform identical source checks and convert the producer material set into one
`SeedManifest`. `admit_seed_manifest` invokes the injected exact evaluator for every source and
returns only locally admitted seeds with Lunar receipts. Remote score, correctness, attempt, and
completion observations do not enter the local evaluation or rank.

No remote state, source, envelope, or archive is mutated by the bridge. Private admission staging
uses the existing seed adapter only under a caller-supplied sibling tree (or its own system
temporary directory); an overlapping staging root is rejected before the adapter can create it.
An empty admitted set preserves the generic `SeedAdmissionError(code="no_usable_seeds")` result
semantics without population mutation.
