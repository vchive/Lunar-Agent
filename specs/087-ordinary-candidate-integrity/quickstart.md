# Feature 087 offline quickstart

1. Run a one-candidate deterministic `PopulationStrategy` in a temporary workspace.
2. Inspect `evolution/candidates/candidate-0001/receipt.json`, `record.json`, and
   `evolution/state.json`; recompute `receipt_sha256` and `candidate_archive_sha256`.
   If the evaluator emits `execution.json`, also recompute and compare its `execution_sha256`.
3. Change one source byte or one authority fingerprint and call `resume()` with generators and
   evaluators that would fail if invoked. Also substitute another valid candidate into
   `active_ids` or `best_candidate_id`; change the RNG, migration, or stagnation projection with
   both wrong values and equality-compatible wrong types; use a projection-inconsistent status; or
   remove the required outcome-binding group and journal while leaving the modern marker visible.
   Repeat the group-removal case after a seeded first offspring batch finishes failed-only without
   an ordinary record. Confirm the fixed integrity, outcome, or population-projection error is
   raised first.
4. Repeat with evaluator timeout, worker uncertainty, source rewrite, and an incomplete archive
   publication. Confirm evaluator/worker failures and a confirmed archive rollback publish no
   candidate receipt. If archive publication and rollback are both uncertain, confirm the fixed
   publication-unknown error retains the source/record/receipt tree for diagnosis while leaving it
   absent from the canonical archive, resume population, and controller index. Confirm no
   secret/prose crosses the durable boundary.
5. Leave a regular `.state.json.tmp` beside a complete pending outcome batch and resume with inert
   callbacks. Confirm state finalizes without replay and the stale temporary is removed. Repeat with
   an incomplete batch and confirm it fails before a generator or evaluator call.
6. For a controller-backed run, confirm ordinary sidecars are indexed as
   `evolution_candidate_record` and `evolution_candidate_receipt`; indexing is idempotent and does
   not make orphan or symlinked files visible. On an outcome append failure, confirm only the exact
   archive prefix bound by the last state digest is indexed. Any process-local feedback overlay
   remains transient.

All steps use local deterministic fixtures and do not run an external framework or model.
