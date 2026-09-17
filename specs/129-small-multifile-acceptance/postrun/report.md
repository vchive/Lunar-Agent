# Feature 129: contract envelope rejected before automatic preparation

The sole registered small automatic multi-file attempt failed at contract intake: **primary
delivery0/1, preparation0/1, holdouts0/8 executed, joint0/1**. No evaluator, candidate or parent
delivery was produced. Official quality/gap are null. The task's known optimum remains3.

Registration08624f593aa07714ef94452ec015811a70e485aa was pushed before starting at
2026-09-17T11:08:30.076900Z. Productb9518570a18e25ad784d00ba864a18ee8e30ac80 stayed fixed;
manifest SHA25663a056263387dbee5c9282fffb21182c9eb2fd51b6354cf871b5d4b06af10ad9.
The sole root is .lunar/acceptance129-glm-5.2-small-multifile-20260917. No retry, resume,
replacement, repair or extra request occurred. Historical campaigns remain sealed.

## Observations

| Item | Retained result |
| --- | --- |
| Provider/model | Registered provider identity, GLM-5.2 |
| Contract request | One request, HTTP200,45.509s |
| Usage | Complete4076tokens:1225input+2851output; cost unknown |
| Request |6268bytes, SHA256641f2b1b84a6e4ec006d1d902d00bf2fcf87007447a32d6488a0fe293ba3aa53 |
| Transport | response_headers_received, HTTP exchange1,45454ms; body14093bytes |
| Private assistant text |2045bytes, complete, no redaction or truncation, zero tool calls |
| Native state | Parent failed; contract-intake task failed; no compiled plan/preparation |
| Supervision |47.339s, worker exit1, cleanup verified, remaining observed PIDs[] |
| Retained evidence |16files,122657bytes |

The ledger records accepted transport/model accounting, independently from native contract
acceptance. Its request response_status is null on this success path; HTTP200 is retained in
the transport sidecar. Neither HTTP200 nor a complete token count means the task succeeded.
local_failure is null because Feature127 evaluator preparation was never reached.

## Read-only diagnosis

The complete captured response is a valid JSON object with exactly the top-level key contract;
contract is an object, but status is absent. The unchanged native parser rejects this with its
fixed message: `compiler response must be status=compiled with contract`. The durable task_failed
event contains that same rejection. The generated private contract is not published or repaired.

Offline reconstruction from the registered goal, isolated system prompt and fixed native contract
prompt yields6268bytes and the exact ledger/transport request SHA. It has system/user messages,
no tools/history,stream:false and native parameter omissions. The existing prompt explicitly
describes `status="compiled"` and `status="needs_input"`; this is not an absent requirement.
It does not provide a complete JSON envelope example. Missing status is a sufficient explanation
for this rejection, not proof of why the model omitted it or that an example will solve it.

Only JSON parsing, native pure response parsing, request serialization and read-only evidence
inspection were used after completion. No model call, evaluator/candidate execution, normalization
repair or summary republication occurred. Original DB/WAL access uses temporary copies. Every
retained file still matches its published size/SHA inventory after diagnosis.

## Interpretation and next work

Feature128's preparation1/1 and holdouts8/8 remain valid within that separate diagnostic. This new
automatic solve still lacks real multi-file success. One failure does not establish overall model
reliability, performance or WebAgent parity.113/115/117/120 remain independently0/2;123/125 remain
independently0/1. No historical denominator changes.

Next add explicit, validated complete compiled/needs_input envelope examples to the contract
compiler prompt, with fresh offline request/parser checks. Preserve strict status and field
validation; do not infer missing status from captured output. Any later real check requires new
registration and a new independent slot. External producer multi-file seeds, end-to-end cancellation
and detached work remain later priorities.

Results: [results.json](results.json). Retained inventory: [evidence.json](evidence.json).
Validation: [validation.md](../validation.md).
