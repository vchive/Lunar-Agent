# Candidate Runner Contract

An explicit runner command is invoked without a shell:

```text
<runner executable> <candidate path>
```

The working directory is the candidate attempt directory. The runner may write regular files below
that directory. To expose output files for hashing, it may also write an
`execution-artifacts.json` array containing portable relative paths to those regular files.
Lunar-Agent validates that manifest, captures bounded stdout/stderr, and writes `execution.json`;
the command must not be trusted to settle validity. A separate evaluator command still receives the
candidate path as its first argument and reads `execution.json` to compute a strict
`EvaluationReport`.

Runner failures, timeouts, malformed paths, and oversized output produce controlled invalid
evidence. No command is discovered through PATH, shell startup files, Hermes/OpenCode/Codex
configuration, or a remote service.
