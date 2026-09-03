# Research: Structured Algorithm Outputs

The existing runtime contract returns text plus optional relative artifact paths, while
`AcceptanceEvaluator` already confines and inspects attempt-local files. That makes a file-based
output contract the smallest compatible extension: models and parent Agents can keep using the
same CLI, and callers receive ordinary local files instead of a provider-specific response shape.

The attempt/run distinction matters. A retry must not read or overwrite another attempt's output,
and a failed attempt must never become deliverable. Promotion therefore happens only after all
base and declarative checks pass. The append-only ledger can retain attempt evidence, while a
stable run-level output path gives downstream tasks and external callers deterministic access.

JSON and JSONL are parsed with the standard library, CSV uses `csv.DictReader`, and text requires
non-empty UTF-8 content. Inspection is bounded by the existing artifact size cap; no content is
placed in events or status metadata.
