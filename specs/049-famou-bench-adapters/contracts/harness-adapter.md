# Contract: Built-in Exact Famou Harness

Invocation:

```text
lunar-agent effect-harness --case-root <private-case-root> \
  [--python <extractor-environment-python>] [--extractor-env NAME] <harness-request.json>
```

The private case root must contain regular non-symlink `tests/extractor_agent.py`,
`tests/evaluator.py`, and `data/`. Its FM-Eval-compatible canonical case content digest, public
projection, and script bytes must match the request's frozen identities. The adapter runs the
extractor once against the candidate workspace and a temporary confined normalized directory,
then runs the evaluator once if extraction succeeds.

The adapter process receives only environment names explicitly allowed by Feature 048. Its
extractor child receives that bounded environment; its evaluator child is created from a fresh
locale/Python base and receives no arbitrary inherited values. The receipt never includes raw
diagnostics, credentials, or private paths.
