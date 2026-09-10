# Feature 071: Correctable Command Argument Diagnostics

## Problem and evidence

Feature 069's terminated postal master attempt contains two `run_command` requests whose nested
`command` value is a string containing a JSON argv array. The existing schema supports both a
real string array and an ordinary command string. The model chose the string branch but embedded
array serialization inside it. `shlex.split` then interpreted `[python3,` as the executable, and
the tool returned a `FileNotFoundError` without explaining how to correct the argument shape.

The runtime did not convert a proper array into a string. The tool schema was present. This is an
opportunity for a specific, useful input diagnostic; it is not evidence that these errors alone
caused the registered master timeout. The active Feature 069 checkout stays frozen.

## P1 story

As a model that accidentally serializes an argv array twice, I receive a clear bounded tool error
showing the expected nested argument type, so my next ordinary tool call can correct it without
an automatic execution, normalization or retry by the tool.

## Acceptance criteria

1. If `command` is a string which, after standard JSON parsing, is an array, reject it before
   subprocess launch with an actionable message: pass the argv array directly without enclosing
   the entire array in a string, or provide an ordinary command string. Show a fixed harmless
   example; never echo the supplied command or its values in this new error.
2. Real arrays retain the existing nonempty string-array validation and exact argv. Ordinary
   strings, including strings starting with `[` that are not JSON arrays (such as the `[` test
   command), retain their `shlex.split` behavior. JSON objects/scalars are outside this diagnostic.
3. Valid JSON arrays encoded as strings are rejected even if empty or containing wrong element
   types. Malformed JSON strings take the existing string path; do not guess, repair, invoke a
   shell, use eval or rerun a failed tool automatically.
4. Keep `allow_exec` as the first gate. Keep deadline enforcement, subprocess environment,
   output handling, success/artifact shape, and tool-call accounting unchanged for runnable calls.
5. Preserve raw model arguments in the transcript. A model may use a later ordinary invocation to
   correct the shape; a deterministic loop test must show two tool calls counted, one subprocess
   dispatch, and no reset of cumulative usage.
6. The diagnostic is static and bounded, and no caller-supplied secret or arbitrary input is
   included. Keep the supported `oneOf` schema and add a short note against quoting an argv array.

## Scope and limits

This changes the error for one recognizable input mistake. It does not silently parse and execute
the nested argv, add transport-level repair, reject all bracket-prefixed strings, change shell
semantics, fix quoting generally, alter master policy, or introduce a model call or benchmark run.
An intentionally JSON-array-looking executable can still be supplied in a real argv array.

Implement on `codex/command-argv-diagnostic`, based on isolated Feature 070. Integrate only after
Feature 069 terminates and its evidence is audited. Historical attempts and their errors remain
unchanged. No real-world solution-quality improvement is claimed by the offline tests.
