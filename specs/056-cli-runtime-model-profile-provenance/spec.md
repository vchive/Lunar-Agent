# Feature 056: CLI Runtime Model Profile Provenance

## Goal

Make the provider-neutral `ModelProfile` usable from the normal CLI agent-loop entry points
without changing one-shot runtimes or the isolated compiler boundary.

## Scope and contract

- `run`, `solve`, `resume`, `answer`, and `plan` accept an optional `--model-profile PATH`.
- The profile file is a bounded regular UTF-8 JSON file parsed through `ModelProfile.from_dict`;
  malformed, unknown, credential-like, or oversized content fails before a run starts.
- A profile is valid only with `--agent-loop` and an OpenAI-compatible runtime. It is passed to
  `HermesSessionRuntime`, so profile timeout, step, token, and cost limits apply at the CLI
  boundary while legacy calls without a profile remain unchanged.
- The controller timeout is capped by the profile timeout; a tighter configured controller timeout
  still wins.
- Detached children receive the same profile path and API keys remain environment-only; profile
  contents and credentials are never copied into command output or durable telemetry.
- The conversational compiler identity fingerprint includes a canonical profile digest, so solve
  resume rejects a changed profile instead of silently continuing under a different policy.
- This feature does not alter one-shot `OpenAICompatibleRuntime`, `run_isolated`, effect adapters,
  or evolution/benchmark-specific runtime flags; those remain separate integration seams.

## Acceptance criteria

1. A CLI agent-loop invocation loads and enforces a valid model profile.
2. Invalid profiles and profile use without agent-loop fail before execution.
3. Detached command propagation preserves `--model-profile` and keeps API keys out of argv.
4. Profile identity is included in the conversational compiler fingerprint used by solve resume.
5. Existing no-profile CLI behavior and all repository quality gates remain green.
