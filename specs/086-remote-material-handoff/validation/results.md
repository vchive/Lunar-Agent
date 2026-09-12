# Feature 086 validation

Completed on 2026-09-13 on the local macOS host. The feature connects a completed,
caller-reconciled remote material observation to the existing producer handoff and local exact
evaluator. It does not start a remote backend, framework, model, provider, scheduler, or campaign.

## Verification

| Check | Result |
| --- | --- |
| Remote lifecycle/producer/Shinka focused suites | 130 passed in 0.21 seconds |
| Full repository regression | 2262 passed in 58.46 seconds |
| Ruff (`src` and `tests`) | pass |
| Python compileall (`src` and `tests`) | pass |
| Specify prerequisites with tasks | pass |
| `git diff --check` | pass |
| Sealed 074/076/078/082 trees | 595 tracked files unchanged |
| Local quickstart | evaluator called once; `usable_count=1`; local score `0.5`; remote run label hashed |

The focused suites cover remote lifecycle reconciliation, completed-state and identity gates,
candidate-source and digest checks, forged frozen DTOs, staging-root overlap and case aliases,
generic producer admission, Shinka SQLite export convergence, score authority, and the no-backend
boundary. Two case-alias fixtures run on this case-insensitive macOS filesystem; they skip on a
case-sensitive filesystem while the remaining assertions stay portable.

Commands used for the final checks:

```sh
./.venv/bin/pytest -o addopts='' -q \
  tests/test_remote_evolution.py \
  tests/test_remote_material_handoff.py \
  tests/test_producer_handoff.py \
  tests/test_shinka_handoff.py
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests
./.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/086-remote-material-handoff" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

The quickstart uses a temporary directory, one fake `RemoteExperimentState`, and one injected
`EvaluationReport`; it reported one evaluator call, one usable seed, score `0.5`, and a
`remote-<sha256>` run label for the colon-containing experiment ID. No source, remote state, or
archive is mutated. A caller-supplied staging root must be a separate sibling tree; an overlap is
rejected before the generic adapter can create it.

## Limits and authority

`RemoteExperimentState` does not contain the original submit contract digest. The caller must bind
the observed experiment to the intended contract; the bridge validates the supplied contract and
uses it for local exact re-evaluation. The state schema also has no parent-lineage field, so the
bridge leaves generic material lineage empty rather than inferring it from IDs or paths.

Remote timestamps, attempts, raw state identity, and score-like evidence are digest-only external
evidence. A validated generic-safe experiment ID may remain as an opaque `producer_run_id` label;
it never supplies a local score, candidate identity, rank, archive entry, or population member.
Only a fresh local exact evaluator receipt can admit a seed. If every material is locally invalid,
the bridge preserves the generic `SeedAdmissionError(code="no_usable_seeds")` result semantics.

The material root is read through the existing descriptor-based regular-file, size, UTF-8,
symlink, FIFO, path-confinement, and SHA-256 checks. The bridge does not fetch references or prove
remote evaluator correctness, dependencies, billing, or transport delivery. Ordinary offspring
receipt/fingerprint completeness remains deferred to Feature 087. Features 084 and 085 remain
Draft, and the 074/076/078/082 sealed measurement artifacts remain byte-for-byte untouched.
