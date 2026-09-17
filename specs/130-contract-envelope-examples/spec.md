# Feature 130: Complete contract response envelope examples

## Problem and outcome

Feature 129 received a complete JSON contract object but no top-level `status`; the strict native
parser correctly rejected it. The compiler prompt already described both statuses, so the result
does not prove an absent rule. Add complete, parser-valid examples for both response branches to
make the required envelope shape concrete while preserving strict admission.

## Acceptance

1. The compiler prompt includes one complete strict JSON `needs_input` envelope with `status`, one
   to four valid questions and optional evidence, and no contract.
2. The prompt includes one complete strict JSON `compiled` envelope with `status`, a complete valid
   contract and optional evidence, and no questions. It demonstrates object-shaped input fields,
   array-shaped output fields and supported evolution values.
3. The prompt labels both examples as shape-only and directs the model to replace their task
   content with facts from the user goal and explicit answer. No placeholders make either JSON
   object invalid or incomplete.
4. The production `_parse_response` accepts both examples. It still rejects a contract-only object,
   unknown fields, duplicate keys, nonfinite numbers, unsupported values and malformed framing.
5. Contract compilation remains one isolated request with no tools, workspace reads, memory or
   previous conversation. No retry, inferred status, response repair or parser relaxation is added.
6. Fresh offline tests and existing framing/intake regression pass without reading Feature 129
   private responses or calling a real model. Historical measurements and denominators stay fixed.

## Limits and follow-up

Examples improve protocol salience but do not prove a model will follow it or that the resulting
contract, evaluator or solver will succeed. Feature 129 remains 0/1. A new real attempt requires a
separate fixed registration committed and pushed before any provider request.
