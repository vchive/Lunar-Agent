# Feature 119: Independently verified source file requirements

## Outcome

Admit one precisely defined source requirement into multi-file evaluation and delivery:
`verification_scope="source"`, `source_check={"kind":"python_file_count","minimum":2}`.
It counts distinct declared bundle paths ending in lowercase `.py`, including empty files.
The check proves file count only, not Python validity, helper imports, usefulness or execution.

## Acceptance

1. Add a strict optional typed source_check declaration; kind must be python_file_count and
   minimum an integer 1..64, never boolean. Only source scope may carry it. Absent declarations
   preserve all historical contract serialization and digests. Intake explains the semantics and
   must not substitute file count for behavioral requirements.
2. Snapshot evaluator preparation admits hard source constraints with this supported check;
   compiler/auditor output probes cover exactly the remaining hard constraints. Explicit execution,
   source without a checker, and soft source requirements remain unsupported before model calls.
   Legacy candidate-path generated evaluators continue rejecting source requirements.
3. Independent candidate evaluation checks the verified full source bundle alongside output
   validation. A source failure creates a deterministic invalid report and skips the output harness.
   Passing source checks cannot override a failing output/harness report. Record bound, deterministic
   source-check evidence; inspection recomputes it without rerunning source or evaluators.
4. Source-aware evaluation records use a distinct protocol and contain source evidence bound to
   contract, full bundle and source table digests. Legacy record requests, manifests and loading stay
   unchanged. Missing/tampered evidence or a downgrade to legacy fields must fail inspection.
5. Native population ranks using the final report. Selected delivery includes source-check evidence,
   full source/contract and existing output report. Portable inspection rechecks source file bytes
   against its manifest and recomputes the checks. Resume/delivery never reruns the candidate.
6. Offline tests cover count failure despite good outputs, source pass/output failure, selection,
   source/evidence tampering, schema and legacy compatibility, compiler coverage, parent delivery,
   terminal resume and zero additional calls. Run full regression after code freeze.

## Limits

No new real model or external framework call, historical slot replay, source imports, behavioral
proof, dependency certification or attestation workflow. A model's declaration is not proof that
it correctly translated a user's requirement; unsupported behavior must remain explicit.
