# Implementation Plan: Durable candidate-generation receipt

1. Trace the existing generator diagnostic payload and controller event persistence path at the
   pinned product commit.
2. Define a small typed payload builder that canonicalizes safe fields and rejects private model
   text, credentials, URLs, and generated source.
3. Persist one event per admitted generation request with atomic Store append and existing run,
   budget, and attempt identity bindings.
4. Add read-only inspection and tamper tests for completion, failure, timeout, duplicate, digest,
   and budget branches; pin historical event inventories.
5. Run the current regression and Feature 139 offline suite without provider calls. Only after the
   product change is pushed may Feature 139 create a new manifest and reconsider registration.

No migration, retry policy, external producer, WebAgent comparison, or evaluator behavior change is
planned.
