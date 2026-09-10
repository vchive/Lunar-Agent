# Feature 073: Deterministic Master JSON Envelopes

## Problem and P1 story

Feature072 slot2 (postal, Master cap1200) returned a 1513-byte final response containing prose
and one json-labelled Markdown code block, then failed after 240.183 subject seconds. Its entire
response fails json.loads at character0; the fenced object has exactly plan/expected_paths.
The frozen runtime parses the entire response before write_master, so no accepted plan or Build
exists. Evidence: Feature072 postrun/observations/slot-002-master-formatting-failure.json, SHA256
f6287636e72d818954d371041173d96e61f78725260b3f0b80e91c4a8954c835. This is independent of the
1200-second limit. As a staged subject, I need deterministic acceptance of an unambiguous JSON
envelope so ordinary Markdown formatting alone does not discard an otherwise valid handoff.

## Acceptance criteria

1. Accept either a whole JSON object (surrounding whitespace allowed), or exactly one line-level
   triple-backtick block labelled lowercase json whose entire body is one JSON object. Optional
   surrounding plain explanation text is discarded. LF and CRLF lines are supported; opening and
   closing delimiter lines permit spaces/tabs around the delimiter, not additional text.
2. Reject extra/unclosed fence lines, unlabelled/json5/yaml/tildes fences, multiple JSON values,
   malformed JSON, scalar/array roots, duplicate object keys and NaN/Infinity constants. In the
   fenced form, reject any brace/bracket characters outside the block, avoiding an arbitrary
   choice among competing objects/arrays. Inline backticks in ordinary explanatory prose are allowed.
   Do not scan for the first object or choose among candidates, repair JSON, or retry a model call.
3. Apply the existing 128KiB UTF8 bound to the complete original response before extracting the
   body. Return only the parsed object; no surrounding explanation reaches Build. Keep all current
   exact-key, bounded-plan, declared-path, forbidden-content, identity and checkpoint validations.
   Do not insert missing fields, normalize unsafe paths, fill candidates or manufacture receipts.
4. Parsing/validation failure keeps the existing failed attempt behavior and recorded usage, with
   no Build, continuation, additional provider/tool call, receipt or harness. Successful handoff
   uses the original task and accepted sanitized plan, preserving shared usage/time/tool ceilings.
   Preserve current known-key/plan redaction behavior; this feature does not claim to detect every
   credential or introduce an unrelated credential-policy change. New parser errors are bounded
   and must not include response contents or decoded duplicate keys.
5. Add failure-first parser tests and real AgentLoop/fake-model integration for prose+json-fence
   success through the existing subject/native trial gate, and ambiguous/unsafe failure with no
   harness dispatch. Keep existing raw-object success and budget tests passing.
6. Implement only in the isolated codex/master-plan-json-envelope worktree. Feature072's main
   product/scripts/tests/input bytes remain frozen. Integrate only after all four attempts terminate
   and their evidence is independently sealed. Do not reclassify or replace any failed attempt.

## Limits

This accepts two explicit envelopes; it is not a general Markdown or JSON repair parser. Other
formats can still fail. Offline success does not prove improved benchmark validity. No real
model call, role/prompt redesign, extra evaluation or historical candidate replay is included.
