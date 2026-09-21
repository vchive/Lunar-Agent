# Feature 145: Lunar Evolution identity migration

**Created**: 2026-09-21
**Status**: Implemented; final regression and publication verification in progress

## User objective

Use **Lunar Evolution** as the product identity and remove the predecessor's name from the
current repository's code, documents, configuration and filenames. The user manages the remote
repository rename separately; its new name has now been observed and origin updated accordingly.
This is a real namespace migration, not a display-only alias.

## Product contract

- Distribution and sole console command: `lunar-evolution`.
- Python package and module invocation: `lunar_evolution`, `python -m lunar_evolution`.
- Configuration environment prefix: `LUNAR_EVOLUTION_`.
- Existing execution-only `LUNAR_*` protocol variables keep their documented meaning; they
  already use this project's namespace and are separate from user configuration variables.
- New default state directory: `.lunar-evolution`; explicit `--home` remains supported.
- Current product prompts, help, User-Agent, internal protocol identifiers, examples, tests,
  exported API names, detached launches and package metadata use the new identity consistently.
- External systems are described as reference engines/benchmarks, not relabeled as this product.
  Required licenses and attribution must remain accurate.

Do not keep predecessor aliases, discover old environment variables implicitly, or assemble
obsolete identifiers from encoded fragments to evade a text scan. Versioned protocol/domain
changes are explicit compatibility changes: old content hashes must not be declared equivalent
to newly named hashes. No provider requests, model campaigns or historical candidate execution.

## Historical evidence and local state

The predecessor namespace occurs inside sealed historical measurements. Preserve the original
bytes in a fixed Git revision and, for private local evidence, an external archive. Retire the
historical measurement implementation/data and dependent tests from the current publication
tree where needed. Keep a neutral index with commit IDs, root paths and integrity digests.
Historical results continue to describe their original product, not the renamed implementation.

Run frozen measurement regressions from that fixed revision in a temporary checkout outside the
repository. Continue the existing frozen registration phase without changing its pins. Current
tests exercise the new package; historical tests exercise their historical product. Both are
required and separately reported, with no hidden skips or rewritten success denominators.

Local predecessor state and test/build artifacts are inventoried and moved outside the current
working tree before fresh setup. Do not merge, rebrand or rewrite database/evidence contents.
Relocation preserves file bytes, not a claim that absolute-path or inode-bound runs can resume.
Explicit access to existing state is subject to the same product identity/path checks as before.
Git history is retained; no force push, tag rewrite or remote repository rename is part of this
task. Retained historical prose may use normalized current terminology; the indexed fixed
revision remains authoritative for original commands, names and evidence.

## Acceptance

1. A case-insensitive scan of tracked text and paths finds no predecessor name. The fresh wheel
   contains only the intended package and console entrypoint. Generated build metadata and local
   launchers are refreshed so an old editable install cannot disguise a packaging error.
2. In a new environment and from outside the repository, imports, CLI/module help, mock run,
   status, events and actual detached execution all succeed. No repository PYTHONPATH is needed.
3. New environment variables work; explicit home takes precedence; a clean invocation uses the
   new default directory. Existing data is retained in the external archive without mutation.
4. Current, archived historical and frozen registration regressions all pass and preserve their
   exact collection inventories. Static checks, links, archive hashes and SDD checks pass.
5. Documentation explains the new installation/configuration and the namespace compatibility
   boundary. No renamed measurement is presented as a new real model result.
