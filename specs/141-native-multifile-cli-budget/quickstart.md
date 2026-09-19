# Offline verification

Feature 141 implements an explicit candidate tool-step budget for native automatic multi-file
solve. Verify the implementation with local parser, handoff, generator, runtime, and receipt
fixtures before any real registration is considered.

The minimum fixture matrix is:

1. A valid automatic solve carrying `--candidate-generation-max-steps 12` persists and forwards
   the value; the runtime sees the resolved candidate timeout and a Feature 136 budget identity.
2. Omitted values preserve the legacy request shape. A changed continuation value and a newly
   supplied value for a legacy handoff are rejected without creating a child or making a request.
3. Unsupported modes reject the option before Store mutation, including standalone
   `evolve-bundle`; its existing loop setting remains unchanged.
4. A profile/runtime with a lower hard ceiling still narrows the effective request, while a
   returned tool batch over the candidate ceiling is atomically rejected and produces no retry or
   candidate publication.
5. A parser-accepted generation produces the matching Feature 140 durable receipt; failure or
   omitted-budget paths do not fabricate one.

After focused tests pass, run the two-stage repository regression, static checks, Specify checks,
`git diff --check`, and independent Feature 131/134 inventories. Do not call a provider, execute
provider-generated source, register Feature 139, or compare WebAgent results during Feature 141
validation. Repository-owned synthetic candidate and evaluator fixtures may execute locally.
