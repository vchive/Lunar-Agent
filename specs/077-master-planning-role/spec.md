# Feature 077: Explicit Master Planning Role

## Problem and P1 story

Feature 076's postal subject produced an accepted Master plan and entered Build. The sheet-metal
subject ended after approximately 1200 aggregate subject seconds without an accepted plan or Build.
Its inspected activity was data discovery and argument corrections, not an observed solver run.
These observations do not establish that a role prompt caused the timeout or that a new prompt
would solve the task. Exact independent Master duration remains unavailable.

There is nevertheless a concrete prompt ambiguity: the staged runner currently sends the complete
normal-mode task first, including instructions to solve, create final files and write a delivery
summary, and appends planning instructions afterwards. The Master has no explicit minimal handoff
condition or instruction to leave unresolved implementation details for Build.

As a staged subject, I need the current planning role to be stated before the later Build task so
I can produce a useful handoff without first completing the requested solution.

## Acceptance criteria

1. Change only the staged Master's user-prompt construction. Put the planning role first, state
   that this invocation's deliverable is a short Build handoff, and identify solving, implementing,
   optimizing and final-file delivery as later Build work. This is role guidance, not a permission
   or read-only capability boundary.
2. Include the original incoming prompt exactly once as a contiguous, unmodified string inside
   visibly labelled Build-task context. Preserve all original Unicode, whitespace, newlines,
   braces, quotes and delimiter-like text. Do not parse, truncate, escape, normalize, search/replace
   or reconstruct the public instruction. The labels help interpret context; they are not a secure
   parser or an instruction-isolation guarantee.
3. After the context, require only the existing exact `plan`/`expected_paths` JSON contract,
   `_agent_summary.md` and existing confined output-path rules. State that only enough public-input
   inspection to choose a starting approach, output paths and public-check plan is needed. Put
   unresolved data or implementation details into plan steps for Build instead of waiting to
   establish feasibility or complete optimization. Stop planning once that minimum handoff exists.
4. Keep the original normal, deep, Build and resume prompts unchanged. The staged runner retains
   the original prompt separately and sends Build that original task plus its accepted sanitized
   plan, never the Master wrapper or raw Master tool history. Existing system prompts, runtime
   budget messages, tool schemas/capabilities, roles, effective deadlines and shared usage accounting
   remain unchanged. Do not change parsers, secret/path checks, schemas or native receipt authority.
5. No extra model call, automatic plan, fallback, retry, replacement, inspection counter, new time
   threshold or altered resume policy. Malformed plan, provider error or budget failure remains
   terminal with the existing evidence/accounting behavior and no unauthorized receipt/harness.
6. Failure-first tests inspect actual AgentLoop model messages and native handoff fixtures: the
   context is intact even with delimiter-like characters, the current role is before it, the exact
   response contract follows it, and uncertainty can be delegated in a valid plan. Verify original
   Build/system/tools/timeouts/usage and failure gates rather than claiming a fake model predicts
   real model behavior.
7. Implement only in the isolated `codex/master-planning-role` worktree based on `1dacddb`.
   Main Feature 076 source, scripts, tests, inputs and registration remain frozen while it runs.
   Independent review and root-owned integration follow evidence sealing; any new real attempt
   needs a separate registration. Existing failed attempts are not restarted or reclassified.

## Evidence and limits

`docs/webagent-master-comparison-20260910.md` identifies the same role distinction: pinned WebAgent
delegates specialist solver work, whereas Lunar appends planning instructions to the normal task.
Its 300-second wait timeout is not Lunar's bounded Master invocation. This feature does not import
WebAgent roles, tools, code, candidate artifacts, historic scores or its multiagent architecture.

The current system and runtime budget guidance remain general-purpose, including candidate-saving
advice and numeric remaining-time information. This feature deliberately tests a narrower user-prompt
clarification. It does not assert missing time awareness, enforce a tool restriction or guarantee
faster handoff, better feasibility, a valid solution or a score.
