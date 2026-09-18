# Measurement contract

Admission sequence: offline verification → registration → commit/push → validate exact registered
bytes and provider identity → exclusively create campaign/slot markers → run one worker → supervise
cleanup → summarize retained evidence once. Reusing a slot or changed registration is an error.

Model stages are contract compiler, evaluator compiler, evaluator auditor, then candidate Agent
requests. The native no-retry flow has no replacement requests or alternate role order. Requests
must respect candidate/ordinary 600 seconds and preparation 900 seconds, clipped by native
preparation wall and remaining campaign time. Request ledger records actual effective limits.

Primary requires complete source-aware feasible parent delivery; secondary requires eight exact
holdout matches; joint additionally requires completed worker, zero exits and verified cleanup.
Partial output or a model success claim cannot establish official quality. Success and failure
reports preserve the denominator and expose safe evidence rather than generated private content.
