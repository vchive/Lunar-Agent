# Tasks: Interactive Session Recovery

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

## Phase 1: Runtime and state

- [x] T001 Add `awaiting_input` run state and input metadata columns/methods.
- [x] T002 Add `ask_user` tool and typed `AgentInputRequired` runtime boundary.

## Phase 2: Controller and CLI

- [x] T003 Persist request/answer artifacts and include answers in the next task prompt.
- [x] T004 Add `answer` CLI command and status JSON/human output.

## Phase 3: Verification

- [x] T005 Add runtime, controller, CLI, dependency-blocking, and safety tests.
- [ ] T006 Update README/contracts/quickstart and run all supported Python versions.
- [ ] T007 Commit as `vchive` and push `main`.
