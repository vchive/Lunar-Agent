# Contract: Normal-Agent Subject v1

Lunar invokes the explicit subject command as:

```text
<subject-command...> <attempt>/subject/request.json
```

with `<attempt>/subject` as cwd. The request contains `mode=normal`, benchmark/case public
identities, the requested model, the public entrypoint and file ledger, and the relative receipt
path `receipt.json`. It contains no baseline score, evaluator/extractor source, private path, harness
command/config, credential, or source-machine path.

The command writes `receipt.json` atomically using the strict subject-receipt schema in
[`../data-model.md`](../data-model.md). It may create solution artifacts anywhere below the subject
workspace except by replacing the frozen request or public case projection. It must not include a
score, validity, arbitrary metadata, raw transcript, or credential in the receipt.

Exit success without a valid completed receipt is a failed logical run. Lunar then does not invoke
the score harness.
