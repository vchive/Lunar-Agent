# Contract: Agent Search Directive

Every Agent generation prompt contains one `search_directive` object with an exact five-mode enum.
The directive must be a pure function of the current `GenerationRequest` and normalized experiment
memory, contain at most eight values in each array, and use no absolute paths or raw data.

Mode instructions:

- `explore`: establish one feasible baseline and a distinct algorithm family;
- `diversify`: avoid cloning archived approaches and try one unexhausted family;
- `repair`: change only what is needed to remove the target's verified errors;
- `refine`: preserve feasibility and improve one declared target metric;
- `recombine`: use parent as baseline and integrate one complementary inspiration trait.

The solver still returns candidate source plus one attributable experiment plan. It does not return
or control the directive, evaluation outcome, lineage, score, or next mode.
