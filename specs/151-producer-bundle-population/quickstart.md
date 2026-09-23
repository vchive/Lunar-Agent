# Feature 151 quickstart

```python
from lunar_evolution import prepare_producer_bundle_drafts

drafts = prepare_producer_bundle_drafts(producer_root, verified_bundles)
for item in drafts:
    native_draft = item.draft
    # Pass native_draft to the configured MultiFileCandidatePipeline explicitly.
```

The adapter reads and verifies the declared source files. It does not write a workspace, call an
evaluator, or treat producer-reported scores as local results.
