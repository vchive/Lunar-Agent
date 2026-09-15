# Validation (draft)

Implementation has not started as of 2026-09-15. No runner, model, provider, evaluator, external framework, remote
service, or campaign may be used to validate this feature.

The implementation gate is a focused offline suite covering:

- canonical digest stability under input/environment ordering and rejection of duplicate keys;
- deep DTO replay and bounds for every identity, evaluator field, and budget value;
- plan/bundle/contract/evaluator/dependency/environment/output pin mismatch before input IO;
- no-follow input paths, bounded reads, missing/changed/replaced files, and private-root checks;
- path-free output and absence of Store/home, process, import, evaluator, archive, receipt, and
  materialization-ledger side effects;
- installed CLI fixture showing successful admission without executing the declared entrypoint.
