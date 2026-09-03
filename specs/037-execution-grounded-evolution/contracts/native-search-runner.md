# Native Search Runner Contract

For native conversational loop/population search, Lunar-Agent invokes every generated `.py`
candidate with the absolute current interpreter and `-I`, without a shell. The working directory is
the candidate archive directory. Verified inputs are copied to their `data/raw/*` paths before
execution. Required and present optional `output/*` files must pass the immutable contract.

A process/output failure returns a strict local invalid report and skips the downstream Agent
evaluator. Successful execution does not itself establish objective quality; it only admits the
candidate to the independent evaluator. Search outputs remain child-run evidence and are never
delivered directly.
