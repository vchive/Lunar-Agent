# Feature Specification: Evolved Output Materialization

**Feature Branch**: `036-evolved-output-materialization`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

`solve --evolve` can compile a natural-language algorithm contract, search with loop, population,
or OpenEvolve, and select an independently evaluated best candidate. It currently stops at the
candidate source path. For a contract that declares CSV, JSON, JSONL, or text outputs, that is not
a complete user result: the selected program still has to run against staged inputs and its data
files must cross the same independent validation and delivery boundary as an ordinary Solver task.

This feature adds a local final-candidate materialization phase. After successful evolution, Lunar-
Agent copies the verified best Python source and staged `data/raw/*` inputs into an isolated,
deterministic attempt directory, invokes it with the repository's Python interpreter, validates
every required `OutputSpec`, and atomically promotes passing files into the conversational intake
run's stable `output/*` namespace. The evolution run retains execution evidence; the intake run
owns delivery metadata. Contracts without `outputs` retain their existing source-only behavior.

## User stories and acceptance scenarios

### User Story 1 — Produce verified data from the evolved program (P1)

1. Given a successful evolution and a contract requiring `output/routes.csv`, when the best
   candidate exits successfully and writes a valid file with the declared fields, then the file is
   promoted to the intake workspace, hashed as `kind=output`, and returned by `solve` and `status`.
2. The selected candidate reads inputs only from its isolated `data/raw/*` copy and writes outputs
   only below its isolated `output/*`; it does not execute in the archive or intake workspace.
3. `deliver` returns the promoted data path only after both process execution and independent
   output validation pass.

### User Story 2 — Fail closed on invalid materialization (P1)

1. A missing required output, malformed format, missing declared field, non-zero exit, timeout,
   path escape, symlink, or oversized file produces a failed materialization record and no promoted
   output.
2. Candidate stdout, an `execution-artifacts.json` claim, or the earlier evolution score cannot
   override final output validation.
3. The `solve` response reports a composite failure while retaining the canonical intake and
   evolution run states for inspection.

### User Story 3 — Resume without duplicate execution or overwrite (P1)

1. A completed materialization is reused only when parent ID, contract digest, candidate path,
   candidate digest, and promoted output digests still match.
2. A terminal failed materialization is inspectable and is not silently re-executed by `resume`.
3. Existing parent output bytes that differ from a newly validated result cause a conflict; they
   are never overwritten. Identical files and ledger rows are reused idempotently.

## Functional requirements

- **FR-3601**: Run final materialization automatically after successful `solve --evolve` only when
  the validated contract declares one or more outputs.
- **FR-3602**: Accept only a confined, regular, non-symlink `.py` best-candidate path whose source
  digest is recorded in the materialization result.
- **FR-3603**: Use a deterministic child-run directory, copy verified staged inputs by size and
  digest, and execute the candidate with the current absolute Python interpreter in isolated mode,
  without a shell or inherited credential environment.
- **FR-3604**: Bound execution time, stdout/stderr, output count, file size, paths, and symlink
  traversal. Retain bounded `execution.json` evidence in the evolution run.
- **FR-3605**: Independently evaluate required outputs and present optional outputs against the
  intake contract's exact path, format, and fields. Earlier candidate evaluation is not authority
  for these files.
- **FR-3606**: Promote passing files atomically to the intake `output/*` namespace, reject
  different pre-existing bytes, record SHA-256/size metadata as `kind=output`, and emit bounded
  `evolved_outputs_promoted` evidence.
- **FR-3607**: Persist one bounded materialization result and parent event containing status,
  contract/candidate digests, execution status, validation decision, and output metadata but no
  file contents, prompts, credentials, or source-machine paths.
- **FR-3608**: Expose materialization through `solve --json` and `status --json`; report composite
  failure from `solve` when materialization fails, even though the separate intake compilation and
  evolution ledgers remain terminal and independently inspectable.
- **FR-3609**: Make `deliver` require a successful, matching evolved materialization for linked
  output-bearing runs and return the stable intake output artifacts.
- **FR-3610**: Keep ordinary `solve`, source-only evolution contracts, direct `evolve`, all three
  strategies, and existing runtime adapters backward compatible.

## Success criteria

- **SC-3601**: An evolved fixture writes a valid CSV or JSON output; the parent has matching bytes,
  one latest hashed output record, a successful materialization payload, and a deliver decision.
- **SC-3602**: Missing, malformed, timed-out, escaped, symlinked, and oversized output fixtures all
  fail closed and never appear as deliverable parent outputs.
- **SC-3603**: Repeating resume performs zero additional candidate executions and detects tampered
  candidate, result metadata, parent output, and conflicting destination bytes.
- **SC-3604**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Executing arbitrary candidate languages, installing candidate dependencies, containers, or hard
  operating-system CPU/memory sandboxing.
- Treating generated tests or candidate manifests as final evaluation authority.
- Retrofitting automatic materialization onto the explicit low-level `evolve CONTRACT` command;
  library callers may invoke the controller boundary directly.
- HTTP/SSE delivery, remote object storage, queues, multi-user isolation, or cloud workers.
