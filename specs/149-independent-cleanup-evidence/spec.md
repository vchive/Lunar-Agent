# Feature 149: independent candidate cleanup evidence

**Status**: Offline implementation slice; no provider or real campaign is authorized

## Problem

The native candidate execution record retains a launch intent, runner result, and completion
descriptor. A successful exit code does not prove that the owned process group was released. The
postrun auditor therefore must keep otherwise complete v1 execution evidence at
`execution_cleanup_unknown` until a separate observation binds process identity, release, and an
independent process-group absence probe.

## Scope

This feature adds a bounded private `cleanup.json` receipt. It is a companion to the existing
three-file execution record and is never folded into `result.json`. The receipt binds the launch
intent and result digests, native/process exit observations, the observed process identity, the
ownership-release identity, and a separate group probe. Its public projection exposes only a
status, fixed reason, and receipt digest; PID/PGID and operating-system details remain private.

The existing v1 record remains readable. A record without `cleanup.json` is recorded but has
unknown cleanup. A failed or unknown cleanup receipt never becomes successful because of a later
completion, score, or delivery artifact. A copied or inode-replaced receipt is unverifiable.

## Contract

The canonical receipt uses protocol `lunar-candidate-execution-cleanup-v1`, schema version `1`,
and fixed fields for the two prior-record digests, native/process exits, observer identity,
release identity, group-probe state, ownership-release state, cleanup outcome,
bounded observation duration, and a self digest. `verified` requires both identities to
match, an `absent` process-group probe, an observed release, and known, matching exits. `failed` and
`unknown` remain non-eligible. Malformed, noncanonical, tampered, relocated, or private-field
receipts are unverifiable with fixed path-free errors.

The completion descriptor includes the no-follow descriptor of `cleanup.json` when present. The
slot auditor accepts that optional file but still requires one execution slot. Native execution
inspection verifies the cleanup descriptor and returns a redacted cleanup summary. The acceptance
auditor promotes the execution boundary only when this summary is verified.

## Non-goals

- No provider request, evaluator invocation, generated-source execution, or campaign launch.
- No migration or rewriting of historical records.
- No inference of cleanup from an exit code, missing process, or a copied byte-identical tree.
