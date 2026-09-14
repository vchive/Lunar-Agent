# Data model

The retained directory contains `result.blob`, `journal.json`, and optional `completed.json`.
The journal binds schema version, parent/child/task, the fixed marker path, result size/SHA-256,
staged device/inode and deterministic terminal artifact ID. The completion receipt binds the
journal SHA-256. All JSON is strict, canonical and bounded; the result stays within 64 KiB.

The child `materialization_publication_prepared` event binds journal/result identity. A commit
transaction adds one child `evolved_materialization` artifact plus `artifact_recorded`, one parent
`evolved_candidate_materialized` event and one child `materialization_publication_committed`
acknowledgement. Execution artifacts are pre-existing, independently checked evidence.

States: absent → prepared → committed → completed. Only a prepared state with a completely absent
terminal batch may complete publication. Partial database evidence is invalid. Committed without
a completion receipt may finish that receipt if the final marker verifies. Completed missing any
required marker/database evidence is invalid. A stage/journal without a prepared receipt is
retained for diagnosis and never used to infer successful execution or delivery.

A present `.completed.json.tmp` is also post-commit evidence: its creation occurs only after the
complete terminal batch was confirmed. It requires a matching marker and committed batch and may
only finish the completion receipt. Recovery syncs an already visible completion receipt and its
directory, since a previous process may have exited after linking it but before directory fsync.
