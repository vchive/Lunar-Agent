# Validation

The API and static CLI were implemented and validated offline on 2026-09-16. The focused
Feature 104 suite passes 195 tests (including the installed CLI fixture); the full repository
regression passes 4471 tests with one existing skip. Ruff, compileall, and the current diff check
pass. No runner, model,
provider, evaluator, external framework, remote service, or campaign was used to validate this
feature.

The implementation gate is a focused offline suite covering:

- canonical digest stability under input/environment ordering and rejection of duplicate keys;
- deep DTO replay and bounds for every identity, evaluator field, and budget value;
- plan/bundle/contract/evaluator/dependency/environment/output pin mismatch before input IO;
- no-follow input paths, bounded reads, missing/changed/replaced files, and private-root checks;
- path-free output and absence of Store/home, process, import, evaluator, archive, receipt, and
  materialization-ledger side effects;
- installed CLI fixture showing successful admission without executing the declared entrypoint;
- static dispatch before config/Store initialization, with plan/pin mismatch and changed-input
  coverage.

The offline gate is complete. This feature still does not run a candidate, evaluator, model,
provider, external framework, remote service, or campaign.
