# Tasks: Explicit Tool Parameter Contracts

- [x] T063-01 Add failing schema and provider-forwarding contract tests.
- [x] T063-02 Add truthful parameter descriptions to the registry.
- [x] T063-03 Run focused/full quality gates and document the v2.5 review.

Validation: four HTTP-boundary regressions fail against the original `tools.py` with missing
descriptions. All 40 focused tests and all 638 repository tests passed after implementation.
Ruff, compileall, build, Specify prerequisites, and diff checks passed. A final wording adjustment
documents the existing UTF-8 cutoff limitation, and the four boundary cases also exercise non-default
command timeout and preview limits. No external model or real evaluation was invoked.

Independent review found no blocking code issue. The existing timeout fixture logs a BrokenPipeError
when its intentionally late response arrives after the client disconnects; tests still pass. Build
emits the existing setuptools license-table deprecation warning. Neither is introduced here.
