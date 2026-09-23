# Implementation plan

1. Define immutable admission item and batch plan DTOs with canonical digesting.
2. Revalidate native multi-file draft structure against the supplied contract digest.
3. Require provenance metadata to match the verified producer bundle projection exactly.
4. Bind all local execution authority digests without trusting producer scores.
5. Export the API and add provider-free no-write and tamper regression coverage.
