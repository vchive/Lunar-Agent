# Tasks: WebAgent Effect Parity Core Loop (Superseded)

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

> Superseded by `003-hermes-inspired-local-agent`. The generic tool-loop and safety tasks below
> were carried forward; WebAgent-specific phase work is intentionally not scheduled.

## Phase 1: Runtime contract

- [ ] T001 Add structured model-turn/tool-call types and OpenAI-compatible response parsing.
- [ ] T002 Implement `AgentLoopRuntime` with step/time limits and event sink.

## Phase 2: Local tools and safety

- [ ] T003 Implement confined `read_file`, `write_file`, and `list_dir` tools.
- [ ] T004 Implement opt-in, no-shell `run_command` with timeout/output limits.
- [ ] T005 Add tool schemas and bounded/redacted event payloads.

## Phase 3: CLI/controller integration

- [ ] T006 Add `--agent-loop`, `--max-steps`, `--allow-exec`, and detached propagation.
- [ ] T007 Add durable Master phases, plan/replan audit files, and `awaiting_input`/answer resume.
- [ ] T008 Ensure tool artifacts and loop events flow through the existing ledger/evaluator.

## Phase 4: Verification and docs

- [ ] T009 Add HTTP fixture loop, limit, safety, orchestration, and CLI tests.
- [ ] T010 Update runtime contract, README, quickstart, and SDD status.
