# Plan

1. Parse and freeze one explicitly supplied receipt before accessing normal configuration or live
   SQLite storage. Reuse 093's bounded DB/WAL copying to obtain a private Store for CLI preflight.
2. Read and validate the complete existing 090 launch identity and ledger ownership. Compare the
   candidate copy and no-follow execution file's canonical bytes, size, device and inode. Probe
   nonce/receipt integrity and refuse any filesystem or database downstream evidence.
3. Acquire the existing nonblocking child lifecycle lock, recheck run workspace/budget and all
   source bindings, then enter 091 publication with the detached receipt. No runner or promoter
   is constructed or called.
4. Embed the receipt in the execution journal, then atomically write the attestation event and
   091 prepared event in one FULL transaction. Register the execution batch through normal 091
   commit and finish its completion receipt. Normal resume revalidates the retained attestation
   and can subsequently continue 092 delivery without running the candidate again.
5. Permit exact explicit retry after a complete attested journal but before SQLite preparation;
   automatic recovery still cannot initiate preparation. Partial/unattested journals and missing
   execution bytes require further diagnosis. Prepared/committed/completion interruptions reuse
   exact evidence, and transaction failure never leaves a consumed nonce without preparation.
6. Extend 093/094 observation to recognize attested journals/events and digest associations while
   keeping nonce, receipt body and execution contents out of reports and exported bundles.

Validation errors precede run-evidence writes. I/O interruption during an authorized publication
may retain journal fragments or complete preparation for later diagnosis/recovery; none are
silently removed. Existing ordinary 090–094 behavior and sealed measurement files remain intact.
