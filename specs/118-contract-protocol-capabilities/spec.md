# Feature 118: Contract framing and evaluator capabilities

## Problem and outcome

117 exposed a complete, schema-valid contract inside an exact Markdown JSON fence, rejected
before execution. Its independent code review also found that output-only synthetic probes
cannot certify source structure or execution behavior, although every hard constraint currently
requires a probe. No response was returned for the timed-out evaluator request; this design
issue is not evidence of its cause.

This feature accepts one precisely framed JSON contract without changing its contents, and
makes evaluator capability limits explicit before spending a compiler/auditor request.

## Acceptance

1. Intake accepts either one raw JSON object or exactly one lowercase `json` code fence with
   LF delimiters and optional outer ASCII JSON whitespace. It bounds/checks the original response, performs
   no extraction from prose or JSON repair, and makes no additional runtime call. Duplicate keys,
   non-finite numbers, unknown fields and invalid contract shapes remain rejected.
2. Constraints may explicitly declare `verification_scope`: `output`, `source`, or `execution`.
   This is independent of `verification` strength and provenance. The compiler prompt asks for
   explicit scope and explains the evidence required. Absence preserves legacy serialization and
   digest; explicit invalid/null values fail. Scope is retained in persisted contracts/digests.
3. Generated bundle evaluators currently support output requirements only. Explicit source or
   execution requirements (hard or soft) fail before any evaluator compiler, auditor, candidate,
   evaluator workspace staging or frozen-bundle loading. The error identifies the constraint IDs and scopes.
   Nothing is silently excluded or reclassified because it is partial or has no result fields.
   Legacy unscoped requirements retain existing complete probe coverage and recovery behavior.
4. Automatic preparation records a bounded, structured `unsupported_constraints` diagnostic and
   an `unsupported_verification` category, with no retry suggestion. JSON/text status explain the
   missing capability, preserve the contract, and do not claim delivery or successful verification.
5. Synthetic parser, compatibility, preflight, CLI persistence and existing recovery tests pass.
   Historical measurements remain byte-identical; there are no real model calls or slot retries.

## Limits

No source/execution checker is invented in this feature. A later capability can admit those scopes
only after its checks are connected to independent evaluation and delivery. Output checks cannot
prove helper imports, standard-library-only execution or actual use of every input. Scope is a
contract declaration, not a proof that free-text requirements were classified correctly; legacy
unscoped contracts keep their prior assumptions. This is an offline product fix, not a new quality
measurement or reinterpretation of the frozen 117 result.
