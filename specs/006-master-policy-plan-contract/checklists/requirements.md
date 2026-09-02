# Requirements Quality Checklist: Master Policy and Plan Contracts

**Purpose**: Review that Feature 006 requirements are complete, unambiguous, and measurable before
implementation is treated as a stable control-plane contract.
**Created**: 2026-09-02
**Feature**: [spec.md](../spec.md)

## Requirement completeness

- [ ] CHK001 Are all six policy actions (`answer`, `ask_user`, `execute_plan`, `patch_plan`,
  `replan`, `deliver`) described with inputs, outputs, and durable-state effects? [Completeness,
  Spec §FR-601]
- [ ] CHK002 Does the specification define how logical plan task IDs map to scheduler IDs across
  creation, revision, recovery, and status inspection? [Gap]
- [ ] CHK003 Are evaluator evidence, artifact digests, and delivery failure behavior specified for
  every task outcome, including partial failure? [Coverage, Spec §FR-610]

## Clarity and consistency

- [ ] CHK004 Is the distinction between a patch (typed operations) and a replan (replacement
  document) explicit, including when each action is allowed? [Clarity, Spec §FR-606–FR-608]
- [ ] CHK005 Are versioning rules unambiguous (exactly one parent, monotonic increment, optimistic
  conflict behavior) for concurrent callers? [Clarity, Edge Cases]
- [ ] CHK006 Do the plan, policy-decision, and patch JSON contracts use the same field names,
  nullability rules, and bounded-size limits? [Consistency, contracts/]

## Scenario and recovery coverage

- [ ] CHK007 Are primary, alternate (`ask_user`), exception (invalid plan/evaluation), and recovery
  (restart/resume) scenarios independently testable? [Coverage, User Stories 1–4]
- [ ] CHK008 Does the specification define revision behavior for succeeded, failed, blocked,
  cancelled, uncertain, and superseded tasks? [Gap, Edge Cases]
- [ ] CHK009 Are migration rollback/recovery expectations documented if the process exits during a
  plan-revision transaction? [Recovery, Gap]

## Non-functional and boundary requirements

- [ ] CHK010 Are local-only deployment boundaries and explicit runtime-adapter configuration
  separated from optional network model usage? [Clarity, Spec §FR-612]
- [ ] CHK011 Are performance targets tied to a reproducible fixture and measured at the CLI boundary
  rather than inferred from implementation details? [Measurability, Spec §SC-605]
- [ ] CHK012 Are secret rejection/redaction rules defined for plan fields, reasons, evidence,
  events, artifacts, logs, and detached process arguments? [Security, Spec §SC-606]

## Notes

This checklist reviews requirement quality; checkbox state is reviewer-owned and does not indicate
whether implementation tests have passed.

