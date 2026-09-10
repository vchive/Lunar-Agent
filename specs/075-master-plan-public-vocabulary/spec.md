# Feature 075: Public Master Plan Vocabulary

## Problem and P1 story

The Feature 074 postal attempt passed Feature 073's JSON envelope parser, then stopped before
Build because its public optimization plan used `objective scorer` and `combined_score`.
`workflow_checkpoint._FORBIDDEN` rejects any occurrence of baseline, private, evaluator, harness,
score or credential in both plan text and declared output names. This also rejects ordinary
baseline heuristics, public evaluators, self-test harnesses, negative instructions about credentials,
and names such as `scorer.py` or `baseline_solution.py`.

As a staged subject, I need to describe public optimization objectives and local checks using their
normal vocabulary, and declare ordinary output filenames, so a valid handoff can reach Build.
Word occurrence is neither a reliable test of evidence provenance nor scoring authority.

## Acceptance criteria

1. Bounded plan text and confined output names may contain any of the former semantic keywords.
   Both `write_master` and `load_master` accept them consistently. Public objective scorers,
   `combined_score`, baseline heuristics, public evaluators, self-test harnesses, and instructions
   not to expose private credentials are ordinary non-authoritative text. `scorer.py`,
   `baseline_solution.py` and similar relative output names are allowed.
2. Keep the exact Master envelope and persisted control schemas unchanged. An additional `score`,
   `overall_score` or `validity_score` field is rejected. Plan text, a local result, readiness or a
   checkpoint never establishes validity or a score. Only the existing subject receipt validation,
   unchanged public projection and exact native harness boundary can do that.
3. Preserve all existing non-lexical validation: bounded nonempty plan items, item count/UTF-8/NUL
   constraints, path count/length/uniqueness, canonical POSIX relative paths, reserved output paths
   (`case/`, `workflow/`, root `request.json` and `receipt.json`), regular-file and symlink/confinement
   checks, manifest identity, digests, state transitions and monotonic resource accounting.
   Checks remain at their existing layers; in particular the staged runner owns reserved output
   names, and the controller validates actual declared files at checkpoint time.
4. Preserve existing plan secret handling: known model keys are redacted before plan persistence,
   generic plan credentials are redacted on write, and stored plans still containing detectable
   credentials are rejected on read. Add a narrow output-path check: reject a path matching the
   existing generic secret pattern on both write and load, and reject a declared path containing
   the model's current nonempty API key at the staged boundary. Never redact or rename a path to
   make it acceptable. Errors must not echo path contents. Ordinary `credential_report.txt` and
   `public_evaluator.py` remain valid names. This adds no new credential syntax or detection claim.
5. Raw and fenced Master envelopes carrying this vocabulary proceed through the existing staged
   Build/checkpoint/resume flow with the same tool and usage accounting. Real schema/path failures
   still retain observed Master usage and produce no Build, receipt, harness dispatch or retry.
   A Build failure remains unscored even when its accepted plan or local text mentions a score.
6. Implement and verify only in the isolated `codex/master-plan-public-vocabulary` worktree based
   on `6d0e0c5`. Main product, scripts, tests and campaign inputs stay frozen while Feature 074
   runs. Do not mutate prior campaign records, retry a failed slot or execute a historical candidate.
   Integration and any new real measurement are separate root-owned actions after evidence sealing.

## Authority and provenance

For this feature, **score-free** describes the control schema and its lack of scoring authority;
it does not ban a word in natural language. Feature 069's prohibition on importing historical
baseline scores, private evaluator content, credentials and raw private paths remains in force.
The subject still receives only its declared public projection. Removing a keyword filter does
not authorize access to private evidence. Actual projection, tool/filesystem boundaries and native
receipt checks retain their existing responsibilities. A text filter could not prove where a
sentence came from; this feature makes no arbitrary-language provenance or OS-sandbox guarantee.

## Non-goals and limits

No parser, prompt, model/profile, role, resource ceiling, resume policy, receipt format, harness,
benchmark, score domain or default workflow changes. No extra provider call, JSON repair, hidden
continuation or automatic retry. Offline fixtures establish handoff and authority behavior, not
benchmark success or improved solution quality. Older accepted control records without detectable
path credentials remain compatible. Secret-bearing output names now fail closed, without evidence
rewrites or path renaming. Old failed attempts are not reopened or reclassified.
