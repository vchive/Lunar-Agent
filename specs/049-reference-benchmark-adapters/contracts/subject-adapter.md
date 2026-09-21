# Contract: Built-in Lunar Normal Subject

Invocation:

```text
lunar-evolution effect-subject [runtime options] <subject-request.json>
```

The adapter accepts only the Feature 048 normal subject request. It resolves `entrypoint` and
`receipt_path` beneath the request directory, runs one fresh Agent loop, and atomically writes the
strict score-free receipt. The Agent may inspect the public case and create solution artifacts in
the attempt workspace. It is explicitly told that it is the SUT and must not score itself.

Endpoint/key configuration is explicit through CLI options or `LUNAR_EVOLUTION_MODEL_ENDPOINT`,
`LUNAR_EVOLUTION_MODEL`, and `LUNAR_EVOLUTION_API_KEY`, which the outer effect command must separately allowlist.
Memory and transcript options are intentionally absent.
