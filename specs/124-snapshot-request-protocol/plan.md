# Plan

Add a pure illustrative request-shape helper next to `_snapshot_invocation_prompt`, using native
input/evaluator serializers for their field sets. Keep the actual contract and profile once in
compiler/auditor context; explicitly mark the example's empty contract and digests as placeholders.
Extend only shared snapshot instructions with descriptor semantics and concrete path mappings.
Existing candidate-mode prompt, strict parsers, request builders and runtime behavior stay intact.

The data model and wire protocols do not change. No dependency or migration is needed. A full
second synthetic contract was rejected because it duplicates context and may confuse task semantics.
Parser relaxation or an input path alias would hide the observed mismatch and change the protocol.
No constitution exception applies.

The first full regression uncovered a version-specific test prerequisite: 24 original registration
fixtures deliberately reject changed product bytes. Keep these pinned tests byte-identical and add
an explicit `tools/run_tests.py` two-stage entry point. Current tests deselect only the exact 24
nodes; an isolated detached 5560eb9 worktree runs those nodes with its own src import path and all
registered pin groups checked. Either phase failure fails the command; temporary worktree cleanup
is unconditional. CI fetches Git history and uses this entry point; document the split rather than
claiming every test ran on HEAD. A hidden pytest hook, guard monkeypatch or historical test edit was
rejected because it would obscure the required registered-product boundary.

Write independent tests comparing the advertised schema with actual requests from both native
paths, including nested input targets, zero-byte inputs and optional output absence. Use a fresh
synthetic evaluator to demonstrate correct target lookup and rejected path lookup, separate from
123 evidence. Run relevant protocol/preflight/production/resume tests and the 112 quickstart.
After review and implementation freeze, run the full regression once, verify historical bytes
directly without running old campaign verifiers, update handoff/readiness/roadmap and commit/push.
