# Agent Generation Contract

The worker receives an `AgentRequest` JSON object from Feature 014. Its role is `solver` by default.
The prompt includes an algorithm contract summary and asks for source only. The response is either:

```json
{"source":"def solve():\\n    ...","filename":"candidate.py","metadata":{"idea":"..."}}
```

or bounded plain source text. The bridge rejects non-success status, malformed JSON objects, empty
source, unsafe filenames, oversized output, and adapter errors. The resulting source is still sent
to the independent validity-first evaluator before it can become a best candidate.
