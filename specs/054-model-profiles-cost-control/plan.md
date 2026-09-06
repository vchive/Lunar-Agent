# Implementation Plan: Model Profiles and Cost Control

1. Extend the existing profile module with a strict, serializable `ModelProfile` policy object.
2. Implement a side-effect-free `UsageLedger` over normalized `RuntimeResult`/subject usage and
   expose immutable aggregate snapshots.
3. Export the new types from `famou`, add focused validation and budget failure tests, and keep
   existing runtime/effect behavior unchanged until a later integration has real effect data.
4. Run focused tests plus repository SDD quality gates.
