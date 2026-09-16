# Plan

Reuse immutable 113 task definitions, independent checkers, holdouts, runtime guard and analysis.
New campaign/worker entry points allocate only 115 roots and pin the repaired product commit.
Pin shared modules and historical manifest/result bytes explicitly. Do not invoke the historical
campaign's prepare, verify, run or summarize functions on a different product version.

`response_guard.py` observes the parsed assistant response inside the existing guard's native-call
boundary. It writes a private sidecar for each returned ModelTurn without changing the native call,
return identity, usage or tool calls. The recorded text is bounded/redacted, not the raw HTTP body
or hidden reasoning. Original text size/hash is retained separately. A diagnostics IO failure is
an advisory unavailable count and never triggers a replacement provider request.

The manifest retains all 113 cases, holdouts, optima, population, sampling and runtime settings.
The same source-file-count limitation and supplemental changed-input holdout interpretation apply.
`delivery_completion` describes verified product delivery, `primary_valid_completion` additionally
requires successful supervisor/worker return, and `registered_valid_completion` adds complete
verified model/budget telemetry. Quality/gap are official only for primary completions; provisional
output checks cannot promote failed slots. Compare each campaign's own /2 count; never pool /4.

114 changed both dispatch and schema guidance. Provider sampling/defaults, cache and time of run
are uncontrolled, and 115 adds passive diagnostics. Observed differences therefore cannot be
attributed solely to invocation isolation. The synthetic cases do not establish general quality.

Before launch, test the new launch routing and diagnostic wrapper, reuse the 113 oracle/guard/
analysis tests, check product and frozen history, and independently review registration. The
product's 5517-passed baseline is already available; measurement-only changes do not require
another complete product run. After launch, inspect every slot and commit/push evidence and findings.
