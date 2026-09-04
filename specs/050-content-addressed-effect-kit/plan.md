# Implementation Plan: Content-Addressed Local Effect Kit

**Branch**: `main` | **Date**: 2026-09-04 | **Spec**: [spec.md](spec.md)

## Technical context

Feature 048 already validates `TrialSuite` and stages ledger-listed public files. Feature 049
already recomputes FM-Eval's case content digest and invokes exact case scripts. The missing piece
is deterministic compilation from local case trees into those existing contracts. The user's
cross-release content-equivalence confirmation changes evidence labeling, not the underlying bytes.

## Decisions

1. **Content identity, not release guessing** — create a local publication digest from selected
   case content/harness/public-ledger identities. The release label is derived from that digest.
2. **Separate provenance sidecar** — `suite.json` remains the closed Feature 048 schema;
   `kit.json` records local-content versus owner-attested equivalence without contaminating the
   evaluator contract.
3. **Public projection by closed role** — copy `instruction.md` plus direct `data/*` only. Alternate
   instructions, tests, ground truth, task metadata, and baselines stay private.
4. **Path-independent canonicalization** — key, canonical content digest, public ledger, and
   harness hashes enter identities; source paths and timestamps never do.
5. **Explicit attestation in the baseline** — a boolean CLI option maps to one fixed authority and
   forced formal ineligibility. It is evidence labeling, not automatic proof.
6. **No new dependency** — use standard-library hashing/copying and existing Feature 048/049
   validators.

## Data flow

```text
owner case root(s)
  -> validate complete private tree / reject LFS pointers
  -> derive content + harness + public ledger identities
  -> suite.json + kit.json + cases/<key>/{instruction.md,data/*}

FM-Eval per-run export + suite.json + explicit owner attestation
  -> baseline authority=owner_attested_content_equivalent
  -> normal EffectTrial report with distinct limitation
```

## Module changes

- Add `famou.effect_kit` for deterministic build and cleanup.
- Reuse `famou_case_content_digest` and strengthen it against LFS pointer content.
- Extend `effect-baseline` with one explicit attestation flag.
- Make EffectTrial comparability vocabulary conditional on baseline authority.
- Add CLI/public exports, README/quickstart, fixture tests, and a local real-case preflight.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No service SDK import or machine Agent discovery. |
| Local-First and Durable State | Pass | All artifacts are local and content addressed. |
| Runtime Adapter Isolation | Pass | Kit construction invokes no model runtime. |
| Artifact-First Verification | Pass | Identities come from case/script bytes. |
| Bounded Autonomy | Pass | One/two explicit roots, new output only, no network. |
| Honest Evidence | Pass | Owner attestation is labeled and formally ineligible. |

## Complexity tracking

One standard-library module and one CLI command. No database, dependency, service client,
publication mutation, scheduler, or evolution change.
