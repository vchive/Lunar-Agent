# Plan

Add shared response/probe/report/source-policy prompt helpers alongside the evaluator parsers.
Use existing constants for numerical bounds, imports and prohibited source constructs. Format
compact placeholder JSON examples for nested schema types; keep contract/profile source text
separate and unchanged. Give exact required/allowed file paths and output coverage IDs for each
contract, with explicit source checks left to the controller. Compiler/auditor keep existing role
prefixes and isolated calls. The auditor receives frozen objective/source, never self probes.

Data model/contracts do not change; existing frozen bundle manifest and report wire protocols are
unchanged. No persistence migration, dependencies or public API needed. Offline121 diagnostics
reconstruct120 requests from pinned Git sources and existing immutable evidence, publish only safe
sizes/counts/digests, and verify the old request hash before reporting measurements. No credentials,
raw response/prompt, additional model calls or evaluator execution enter these diagnostics.

Alternative rejected: increase600-second deadline again; split compiler into more requests before
measuring its exact input; loosen strict parsing; remove difficult constraints; infer timeout cause
from absent responses. Future diagnostics must be independently registered after product freeze.

Tests should exercise protocol examples through actual envelope/probe/source/report parsers,
compiler/auditor isolation, schema-valid negative probes, source-aware pipeline and frozen resume.
Run targeted tests and112 quickstart, freeze implementation, then one full product regression.
Independent review, docs/links/Specify/Ruff/compile checks and normal commit/push finish the feature.
No constitution exception; arbitrary registered contracts may still exceed current probe capacity.
