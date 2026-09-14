# Feature 084 validation

Completed on 2026-09-14 on the local macOS host. Feature 084 provides the bounded verified-seed
adapter and transport-free remote lifecycle contract. Later producer adapters and the Feature 086
remote-material bridge converge on the same local exact-evaluator gate. This validation did not
start a model, provider, OpenEvolve/ShinkaEvolve process, WebAgent, remote service, company
evaluator, scheduler, or campaign.

## Verification

| Check | Result |
| --- | --- |
| Seed/remote/producer/evolution/controller/CLI focused suites | 507 passed in 10.91 seconds |
| Full repository regression | 2673 passed in 78.26 seconds |
| Ruff (`src` and `tests`) | pass |
| Python compileall (`src` and `tests`) | pass |
| Specify prerequisites with tasks | pass |
| `git diff --check` | pass |
| Sealed 074/076/078/082 trees | 595 tracked files unchanged |
| Independent Feature 084 evidence review | no remaining implementation or behavior blocker |

Commands used for the closure checks:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_seed_handoff.py \
  tests/test_remote_evolution.py \
  tests/test_openevolve_handoff.py \
  tests/test_remote_material_handoff.py \
  tests/test_producer_handoff.py \
  tests/test_evolution.py \
  tests/test_cli.py \
  tests/test_agent_evolution.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/084-verified-seed-handoff" \
  bash .specify/scripts/bash/check-prerequisites.sh \
  --json --require-tasks --include-tasks
git diff --check
git ls-files specs/074-* specs/076-* specs/078-* specs/082-*
git diff --name-only HEAD -- specs/074-* specs/076-* specs/078-* specs/082-*
```

The focused tests cover strict manifest parsing and bounds, stable seed identity, local evaluator
receipt generation, exact-harness enforcement for external material, digest-only producer
evidence, mixed and all-invalid batches, private staging, identity collision, source mutation,
atomic seed publication, fresh resume admission, contract/evaluator/dependency/environment and
provenance drift, controlled initialization failures, and non-mutating rejection before generator
or population work. The remote lifecycle fixtures cover all five protocol operations, opaque IDs,
bounded credential-safe DTOs, legal and unknown reconciliation, terminal immutability, and
single-call uncertainty without invented completion. OpenEvolve, generic producer, and remote
material fixtures prove that external scores cannot set a Lunar report, rank, archive record, or
population member before the injected local evaluator succeeds.

## Limits and authority

The receipt and canonical digests provide local self-consistency, not external authenticity. A
caller supplies the declared dependency and environment identities; Feature 084 compares and binds
those values but does not install dependencies or prove transitive host state. Material references
are opaque labels whose normalized list is hashed; only the separately declared candidate source
bytes are read and verified. The remote protocol has no transport, endpoint, credentials, retry
loop, billing authority, or score authority. Feature 086's bridge still requires a caller to bind a
completed remote observation to the intended contract because the lifecycle DTO does not carry the
submit contract digest.

No effectiveness or WebAgent-parity conclusion follows from these offline checks. Any real
framework execution, remote backend, provider use, or effectiveness measurement requires its own
explicitly scoped and frozen feature or campaign.
