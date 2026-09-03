# Contract: Offline FM-Eval Baseline Converter

Invocation:

```text
lunar-agent effect-baseline <results.json> <suite.json> <baseline.json> \
  --experiment-id fmexp-... \
  --requested-model gpt-5.6-sol \
  --effective-model openai/gpt-5.6-sol \
  --model-evidence not_observable
```

The input is an owner-authorized local copy of the FM-Eval experiment results response. The
converter performs no network call. The export must carry its experiment identity; the converter
verifies it, emits only cases selected by the suite, normalizes run/status vocabulary, and writes
the exact strict Feature 048 baseline atomically.

There is no score, best-score, or aggregate CLI option. An existing output is not overwritten.
