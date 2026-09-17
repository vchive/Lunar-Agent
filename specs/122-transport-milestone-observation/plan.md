# Plan

Wrap standard-library HTTPConnection/HTTPSConnection connect/request/getresponse methods using
super with unchanged arguments. Override HTTPHandler/HTTPSHandler do_open only to substitute the
observed connection class; retain inherited https_open and context construction across Python3.11+.
Do not copy urllib networking internals or introduce another TLS context, retry or streaming path.

Extend anonymous worker stdout with small milestone frames alongside the old phase/terminal frames.
A strict shared progress parser validates each sequence and retains only its latest typed snapshot.
At most256 milestone frames plus one explicit observation-unavailable frame (also used if the
observation clock is invalid); terminal payload stays unchanged. Deadline decoding consumes complete
valid progress without accepting any late success.
Corrupt IPC remains a fixed transport failure; optional subject projection failure falls back to v4.

TransportResponse/TransportFailure gain optional observation defaults. Runtime retains that snapshot
on ModelRequestFailure; ModelRequestObservation and successful ModelTurn remain unchanged. Subject
schema5 adds transport_observation with exact fields and independently validates it; no old artifacts
are rewritten. No new dependencies, data migration or constitution exception.

Tests divide into strict IPC/unit tests, real loopback transport fixtures, and runtime/subject
projection compatibility. Run related regressions and112 quickstart, review, freeze implementation,
then full suite and static/docs checks. Commit and push the verified product under existing authority.

Next measurement design (not registered or executed here): one small synthetic typed snapshot
contract, one compiler and conditional auditor (max2 requests),600s/request and a supervisor-enforced
task wall, predeclared holdouts executed only after evaluator freeze. It must be separately committed/pushed
before requests and use its own /1 denominator. It tests evaluator preparation, not full task quality
or a causal comparison with121. Raising timeout or changing stream:false is not part of this plan.
