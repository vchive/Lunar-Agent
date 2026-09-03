# Research: Runtime-Backed Evolution Agents

## Existing seam

`RuntimeAgentAdapter` already turns any repository `Runtime` into a role-bearing `AgentAdapter`,
while `AgentCandidateGenerator` and `AgentCandidateEvaluator` enforce bounded prompts, result
status, and candidate/report schemas. The evolution CLI currently constructs only command-backed
adapters, so the missing work is explicit runtime construction, provenance, and detached argument
propagation.

## Decision

Add one optional `--agent-runtime` profile to `evolve`. Build a fresh runtime adapter per role so
solver and evaluator requests never share mutable runtime state. Explicit options fill their seam;
the runtime fills any unbound seam. Runtime provenance is hashed with the same credential-safe
fingerprint boundary already used by command adapters. Detached children receive non-secret settings
as arguments and API keys through `FAMOU_AGENT_RUNTIME_API_KEY`.

## Alternatives considered

1. **Require a wrapper command** — rejected because it undermines standalone distribution and makes
   every local model setup adapter-specific.
2. **Import Hermes/OpenCode SDKs** — rejected because the repository must remain independent of
   machine-global Agent installations and third-party runtime packages.
3. **Reuse one mutable runtime instance for both roles** — rejected because concurrent/long-running
   runtimes may retain process or session state across solver and evaluator calls.

## External harness review

The repository was also compared with the publicly available harness surfaces of
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness),
[Claude Code](https://github.com/anthropics/claude-code), and
[Codex](https://github.com/openai/codex):

| Harness | Useful boundary | Why it is not the default Lunar-Agent runtime |
|---|---|---|
| DeepSeek Harness | Cordis plugin composition, headless/SDK/ACP profiles, lifecycle events, session event log, sandbox and subagent providers | A Node/TypeScript developer-preview platform with a broad plugin surface; embedding it would make the Python local controller depend on another runtime and its breaking-change cadence. |
| Claude Code | Feature-development workflow, hooks/plugins, multi-reviewer flow, and persistent Ralph-style loop | The core runtime is not exposed as a small embeddable library, and the repository is governed by Anthropic commercial terms. It is best treated as an explicitly invoked external adapter. |
| Codex | Apache-2.0 Rust implementation, non-interactive `exec`, MCP, sandbox policy, and app-server/JSON-RPC protocol | The core is a large Rust workspace. The stable integration value is its process/protocol boundary, not vendoring the whole execution core into this Python package. |

The common lesson is to separate a control plane from an execution plane. Lunar-Agent owns the
durable run/task ledger, SDD plan revisions, evolution archive, evaluator authority, validity-first
selection, artifact confinement, and resume checks. Any of these harnesses can be an explicit
subprocess, endpoint, ACP, or app-server provider behind the runtime/Agent adapter, but none is
required for a standalone install. This preserves the user's three invocation modes: direct local
agent, child process called by another Agent, and controller delegating to an explicitly selected
worker.
