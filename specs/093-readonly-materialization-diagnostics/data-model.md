# Data model

No new persistent records. The report is printed to stdout only.

Schema 1 identifies the requested parent/evolution run IDs, overall inspection status
(`observed`, `attention_required`, `busy`, `unavailable`), five stage observations and fixed issues.
Each stage lists fixed file keys with presence/shape information and relevant ledger counts.
`recovery_eligibility` is always `not_assessed`; the report never returns a `can_resume` flag.
Next-step text comes from fixed strings, never from retained files or database payloads.

Source-byte reads and SQLite queries are bounded. Private temporary database/WAL copies are
ephemeral and never become run evidence. Access-time updates from ordinary reads are permitted;
source contents, mtime, directory entries and business records must remain unchanged.
