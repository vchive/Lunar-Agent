# Feature 139 independent postrun audit

## Decision

The retained evidence supports the published result: preparation succeeded, but the sole real
attempt did not produce a completed candidate or an end-to-end delivery. `primary_success=0/1` and
`joint_success=0/1` are correct. No later artifact can upgrade either failed generation receipt.

## Read-only method

The audit inspected the committed manifest, request and transport ledgers, native trace, terminal
records, public results/inventory, retained workspace, and Store evidence. SQLite inspection used
the measurement's read-only-copy API where database queries were needed. No provider, candidate
runner, evaluator, holdout, registration, admission, resume, repair, or second summarization was
invoked. The registered retained-file inventory was recomputed after inspection.

The retained campaign contains one registration, one admitted `attempt-001`, and one worker
terminal record. The evidence inventory contains 70 files totaling 298462 bytes, including 17
response records and one `state.db`; no retained WAL or SHM file exists. Inspection did not change
the retained bytes.

## Ledger and budget findings

- Exactly 17 provider requests finished: three preparation requests and 14 candidate-generation
  requests across two candidate invocations.
- Every request has a bound transport record with HTTP 200. `calls.jsonl`, `transport.jsonl`, and
  `results.json` agree on identity, completion, status, and known usage.
- Known usage is 72315 input tokens, 63029 output tokens, and 135344 total tokens. There are no
  pending requests; cost remains unknown.
- The request count, observed-token threshold, 3000-second wall limit, and per-request limits were
  not exhausted. The official result has `stopped_reason=null` and no request, wall, or local
  failure projection.
- Total elapsed time is 811.740448 seconds. Native and supervised process exit codes are 1.
  Cleanup is verified and the terminal evidence reports no observed live PID.

## Native stage-chain findings

The contract and frozen evaluator/profile identities verify. Preparation reached `profile_publish`
and is not recoverable. The six-stage product chain stops at candidate generation:

1. Preparation: verified.
2. Candidate generation: two durable failed receipts, `worker_failed` then `malformed_candidate`.
3. Candidate execution: absent, as required after no completed candidate.
4. Independent scoring: absent.
5. Validity-first selection: absent.
6. Parent delivery: absent.

The second final response is not a strict JSON object: it adds prose and a Markdown fence, and two
fields use object values instead of the required arrays. Rejecting it is consistent with the
production parser. Files in either generation scratch directory are untrusted partial work; none
has a parser-complete receipt, execution identity, score, selection, or delivery authority.

The evolution result is `offspring_batch_failed`, with zero completed, evaluated, and valid
candidates. The worker's final `holdout_gate` failure correctly prevents all eight planned
holdouts. Public `output_unavailable`, null quality/gap, failed effective product status, and
succeeded persisted parent intake status are mutually consistent.

## Limitations and follow-up

The first receipt exposes only `worker_failed`; retained public evidence does not identify the
lower-level worker cause. Tool-step used/remaining fields are null in both failed generation
receipts, so this audit does not attribute either failure to exhausting the registered 12-step
budget. Future product work should preserve a bounded typed worker failure and make the strict
final-response contract more reliable without repairing this historical response.

Feature 131/134 remain separate frozen measurements. This audit adds no claim of current automatic
multi-file success, WebAgent parity, general quality, or external producer effectiveness.
