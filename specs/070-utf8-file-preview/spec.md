# Feature 070: UTF-8 File Preview Boundaries

## Problem and evidence

During registered Feature 069 slot 2, `read_file` rejected the valid UTF-8 public file
`case/data/opi_points.csv` as invalid text. The complete file is 28,878 bytes; the first 20,000 bytes
end at byte 20,000 inside a multibyte character starting at offset 19,998. `_read_file` currently
truncates raw bytes and then decodes with `final=True`, treating an artificial preview boundary as
the end of the source file.

This explains one observed tool error. It does not establish how much time the error consumed or
why the whole master stage failed. Feature 069 remains frozen and runs to completion unchanged.
This feature is developed in a separate worktree and cannot be merged into the measured checkout
until the registered campaign has terminated and its evidence has been audited.

## P1 story

As a model inspecting a valid UTF-8 file, I receive the longest complete-character prefix fitting
the existing byte limit even when the next character crosses that limit, so I can inspect input
without an erroneous encoding failure.

## Acceptance criteria

1. For a file larger than `max_output_bytes`, decode the limited prefix strictly while allowing
   an incomplete trailing UTF-8 sequence at the artificial cutoff. Omit only that incomplete
   character; retain all prior complete code points and append the existing truncation marker.
2. Cover every interior cutoff of two-, three- and four-byte code points, including an empty
   preview when the first character exceeds the limit. Never insert a replacement character.
3. Invalid UTF-8 inside the visible prefix remains a tool failure. If the file reaches actual EOF
   at or below the limit, an incomplete final sequence also remains a failure.
4. ASCII, empty and complete UTF-8 files retain their existing output; a file exactly at the
   limit has no truncation marker. Content bytes remain within the configured byte limit, with
   the existing marker allowed outside that limit as before.
5. Keep the tool name, arguments, result/artifact schema, path confinement, command execution,
   receipt and harness authority unchanged. Update only the preview-boundary schema explanation.
6. Tests use temporary synthetic files and no model/provider. Do not execute historical model
   commands, copy old candidates into new runs, mutate Feature 069 evidence or alter its slots.

## Non-goals and limits

No encoding detection, lossy replacement/ignore decoding, pagination, whole-file validation claim,
streaming file reads, command-argument normalization, master-policy change or evaluation retry.
Only the preview is checked for a truncated file; bytes beyond that prefix remain unexamined.
Existing whole-file read behavior and maximum-output configuration remain unchanged.

## Success measure

Deterministic boundary tests pass and the synthetic 20,000-byte reproduction returns the valid
19,998-byte prefix plus the existing marker. Improvement in real solving or valid-solution rate
requires a separate future registration and is not a completion criterion for this bug fix.
