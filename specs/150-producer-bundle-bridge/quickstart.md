# Feature 150 quickstart

The bridge is a Python API because it is a preparation boundary, not a producer launcher. A
caller creates a completed `ProducerResultEnvelope`, declares explicit groups, and passes the
producer material directory to `prepare_producer_bundle_manifest`:

```python
from lunar_evolution import BundleGroup, prepare_producer_bundle_manifest

bundles = prepare_producer_bundle_manifest(
    external_root,
    envelope,
    [BundleGroup("candidate-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
    contract,
    producer_fingerprint,
    producer_id="producer",
)
```

The returned bundle can be handed to the existing local bundle pipeline after the caller chooses
that integration. Preparation does not run the candidate or evaluator. Any source mutation,
missing declaration, overlap, identity mismatch, or unsafe path fails closed.
