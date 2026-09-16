# Feature 110 quickstart

From the repository root, with the project installed in `.venv`:

```sh
.venv/bin/python specs/110-agent-bundle-generation/quickstart.py
```

The standalone script creates a temporary contract, input and pinned local evaluator profile. It
runs `evolve-bundle --agent-runtime subprocess` using a deterministic local worker, which receives
the Agent prompt and reads verified context files from its fresh workspace. The worker changes
only the parent helper and returns the complete source map. The normal candidate runner/evaluator
independently scores each proposal; generated score claims are ignored. It then inspects the full
delivery and resumes the completed run, asserting that Agent/candidate invocation counts do not grow.

The fixture is local and makes no model or network calls. It remains on disk for inspection and does
not establish real-model effectiveness. Its dependency/environment digests identify explicit fixture
declarations; they do not authenticate installed packages or the host interpreter.

For an existing explicit bundle profile, users can select a native model runtime directly:

```sh
lunar-agent evolve-bundle contract.json --profile profile.json --workspace ./bundle-run \
  --agent-runtime openai-compatible --agent-runtime-endpoint YOUR_ENDPOINT \
  --agent-runtime-model YOUR_MODEL --agent-runtime-loop \
  --destination-root ./deliveries --json
```

The existing destination root must be outside `bundle-run/evolution`. Use the loop when the Agent
needs to read staged inputs and complete parent files through the repository's tools. Supply any
credential through the existing runtime environment configuration. This remote example is a usage
template; it is not executed by the quickstart or this feature's validation.

Alternatively, `--agent-command '/absolute/python /absolute/agent.py'` uses the existing JSON
AgentRequest stdin interface. A command worker can return a complete `{entrypoint, files, ...}`
object directly or place that JSON in an AgentResult `text` field. `--generator-command` retains its
Feature 109 request-file protocol. Choose exactly one generation mode; resume with the same mode,
profile and settings plus `--resume --run-id ID`.

Complete source is available in `context/parent/files.json` and as separate files below
`context/parent/source/`. Declared input bytes are in `context/inputs/`; generated candidates read
their independently staged copies through `LUNAR_CANDIDATE_INPUT_ROOT`. The fixed evaluator remains
authoritative and its implementation is not copied into the Agent's context.

Validated on 2026-09-16 by running the command above unchanged. Independent scores were
`1, 2, 6, 7`, with four distinct bundle identities and unchanged entrypoint bytes. Delivery contained
the 7-point helper/output/report. Before and after terminal resume, Agent and candidate invocation
counts both remained `4`. All assertions passed; the process exited with code `0`.
