# Feature 112: Automatic evaluator preparation for multi-file solve

## Outcome

`solve GOAL --evolve --multi-file --input SOURCE[=TARGET]` compiles and independently probes a
fixed local evaluator, prepares the existing bundle pipeline, and uses Feature 111's generation,
selection and parent delivery. Users no longer write the evaluator source or pipeline profile.

## Acceptance

1. Reuse the existing evaluator compiler, separate adversarial auditor, bounded source/envelope
   checks, constraint probes and score-order probes. Add a native snapshot invocation that reads
   the Feature 108 request, inputs and outputs. Preserve all legacy invocation behavior.
2. Freeze evaluator mode and complete materials before candidate generation. Generate an ordinary
   bundle pipeline profile using exact registered inputs, the local Python interpreter, explicit
   environment and bounded execution/evaluation settings. Include preparation artifacts in the
   parent budget. Generated dependency/environment pins describe configuration, not installed
   package or host authentication.
3. Persist prepared profile/evaluator identities in existing Store artifacts/events. Reuse frozen
   material after interruption without a model/compiler/auditor call. Once prepared or linked,
   missing or conflicting profile/evaluator evidence cannot authorize regeneration.
4. Resume and answer infer the stored automatic mode; validate retained preparation before answer
   or input mutation. Explicit mode conflicts fail early. Legacy single-file and explicit bundle
   profile modes remain compatible.
5. The solver sees contract, inputs, complete parent source and independent feedback; generated
   evaluator implementation/probes/audit remain outside its staged context. Existing independent
   candidate evaluation and selected parent delivery remain the only scoring/delivery path.

## Scope

Native population, local Python execution and existing registered input formats. No
dependency installation, external producer, detached bundle solve, active-process cancellation
orchestration, real provider/framework measurement, or new attestation. Synthetic probes establish
the tested behaviors and do not prove that a generated judge captures all business semantics.
