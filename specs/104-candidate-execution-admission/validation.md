# Validation

The core API was implemented and validated offline on 2026-09-16. The focused Feature 104 suite
passes 190 tests; the Feature 102/103/104 combined suite passes 456 tests with one existing skip.
Ruff, compileall, and the current diff check pass for the implemented core. No runner, model,
provider, evaluator, external framework, remote service, or campaign was used to validate this
feature.

The implementation gate is a focused offline suite covering:

- canonical digest stability under input/environment ordering and rejection of duplicate keys;
- deep DTO replay and bounds for every identity, evaluator field, and budget value;
- plan/bundle/contract/evaluator/dependency/environment/output pin mismatch before input IO;
- no-follow input paths, bounded reads, missing/changed/replaced files, and private-root checks;
- path-free output and absence of Store/home, process, import, evaluator, archive, receipt, and
  materialization-ledger side effects;
- installed CLI fixture showing successful admission without executing the declared entrypoint
  (pending T104-04/T104-05).

The remaining gate is the static `candidate-bundle admit-execution` dispatch, including its
no-home/no-Store fixture and plan/pin mismatch coverage. Until that gate lands, the command in
the quickstart is the reserved interface rather than an installed-CLI guarantee.
