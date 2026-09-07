# Feature 057: Effect Subject Model Profile Provenance

## Goal

Make the isolated Famou-Bench subject adapter use the same bounded `ModelProfile` policy as the
ordinary CLI agent loop, while preserving score authority in the private harness and making
resume fail closed when the profile changes.

## Scope and contract

- `effect-subject` accepts an optional `--model-profile PATH`. The file is a bounded regular UTF-8
  JSON object parsed through `ModelProfile.from_dict`; malformed, unknown, credential-like, or
  oversized content fails before the subject runtime starts.
- A supplied profile must name the generated request model. Its `max_steps` and
  `timeout_seconds` govern the subject runtime; explicit legacy limits may only tighten those
  bounds. The profile is passed to `AgentLoopRuntime` so token and cost ceilings are enforced.
- Subject receipts remain score-free. They may expose only credential-free profile identity and
  runtime telemetry: profile digest, requested/effective model, model evidence, interaction turns,
  normalized token usage, and cost when prices are configured. API keys never enter profile files,
  receipts, reports, or child command arguments.
- Normal and deep effect trial requests and durable identities include the canonical profile digest
  (or an explicit absence marker). Resume rejects a changed or unexpectedly missing profile.
- Deep-round receipt validation binds each score-free subject receipt to both its request digest and
  profile digest. Private evaluator inputs and scores remain inaccessible to the subject process.
- Existing invocations without a profile remain backward compatible, but they retain the legacy
  timeout and step limits and do not claim profile provenance.

## Acceptance criteria

1. `effect-subject --model-profile` loads and enforces a valid profile, including token/cost
   ceilings, while rejecting model mismatches and invalid profile files before execution.
2. Subject receipts and trial reports contain no score from the subject and include only bounded,
   credential-free profile/usage provenance.
3. Normal and deep trial resume identities and round receipt checks fail closed after profile
   changes or profile/request mismatches.
4. API keys are absent from profile-derived command lines and durable JSON artifacts.
5. No-profile behavior and all repository quality gates remain green.
