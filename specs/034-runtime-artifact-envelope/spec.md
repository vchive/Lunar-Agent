# Feature Specification: One-shot Runtime Artifact Envelope

**Feature Branch**: `034-runtime-artifact-envelope`  
**Created**: 2026-09-03  
**Status**: Implemented  
**Input**: A one-shot OpenAI-compatible response can explain a result but cannot create the files
required by an algorithm or role evidence contract when no tool loop is enabled.

## Context and scope

The local controller already owns file validation, promotion, hashing, and delivery. This feature
adds a narrow response protocol for runtimes that cannot execute tools: a model may return one
JSON artifact envelope containing final text and bounded UTF-8 file contents. The runtime writes
those files only beneath its private attempt workspace and returns their relative paths through the
existing `RuntimeResult` contract.

This is not a general model filesystem API. Absolute paths, traversal, symlinks, duplicate paths,
oversized content, unknown envelope fields, and malformed artifact entries fail closed. Tool-capable
`AgentLoopRuntime` remains unchanged and can continue to write files incrementally.

## User stories and acceptance scenarios

### User Story 1 — Produce data without a tool loop (P1)

1. Given a task prompt that permits an artifact envelope, when an OpenAI-compatible model returns
   `{text, artifacts}`, then the runtime writes each declared file into the attempt workspace.
2. The controller evaluates and promotes declared Solver outputs exactly as if a tool-capable
   runtime had written them.
3. A normal prose response remains a normal text result for backwards compatibility.

### User Story 2 — Keep envelope writes confined and bounded (P1)

1. Given absolute, traversal, symlinked, duplicate, non-string, or oversized entries, when the
   envelope is parsed, then the runtime fails without writing an unsafe file.
2. Artifact contents and metadata are not copied into events; only existing result/artifact hashes
   and bounded scalar metadata are persisted by the controller.

### User Story 3 — Preserve parent-Agent interoperability (P2)

1. `RuntimeResult.artifacts` lists the files written by the envelope so the normal artifact ledger
   records them as runtime/role/output evidence.
2. The protocol is available to any explicit OpenAI-compatible endpoint and does not inspect global
   Hermes, OpenCode, Codex, or OpenClaw state.

## Functional requirements

- **FR-3401**: Recognize only a strict JSON object containing `text` and `artifacts`, with optional
  string `metadata`; ordinary non-envelope text remains unchanged.
- **FR-3402**: Limit envelopes to 32 files and 256 KiB total UTF-8 content; each path is portable,
  relative, non-empty, and confined below the attempt workspace.
- **FR-3403**: Reject symlinked workspace components and never follow a symlink while writing.
- **FR-3404**: Write files atomically and return deduplicated relative paths in `RuntimeResult`.
- **FR-3405**: Add bounded envelope guidance to structured task prompts without changing tool-loop
  semantics or requiring an envelope from models that can use tools.
- **FR-3406**: Preserve runtime metadata compatibility and redact/reject credential-like metadata.
- **FR-3407**: Keep old one-shot compiler envelopes (`status`, `contract`, `questions`) untouched;
  they are not artifact envelopes because they lack the required `artifacts` member.

## Success criteria

- **SC-3401**: A fake OpenAI endpoint returning a valid envelope produces files and a successful
  structured-output task without `--agent-loop`.
- **SC-3402**: Unsafe or oversized envelope paths/content fail closed with no outside-workspace file
  created.
- **SC-3403**: Existing prose, compiler, tool-call, runtime, and full controller tests pass.
- **SC-3404**: Full tests, lint, compile, diff, and Specify checks pass.

## Out of scope

- Streaming/multipart envelopes, binary/base64 files, arbitrary shell execution, or remote object
  storage.
- Inferring output schemas or bypassing `OutputSpec`, role acceptance, or independent evaluators.
