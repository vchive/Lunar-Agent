"""120 task wording; mathematical inputs, oracle and holdouts stay frozen in 113."""
from copy import deepcopy

from tasks import CASES as HISTORICAL_CASES

COMMON_GOAL = """
Deliver a complete Python source bundle containing at least two distinct paths
ending in lowercase .py. This is a hard source-artifact requirement: represent
it as verification_scope=source and source_check={"kind":"python_file_count",
"minimum":2}. All other hard constraints above concern output values and use
verification_scope=output. The source check counts declared delivered files,
including empty files; it does not require an imported helper or particular
runtime dependencies, nor does it attest which inputs the program read.
The registered JSON values define the mathematical problem. Produce both
required JSON outputs at the declared output/ paths. All IDs are exact,
case-sensitive strings. All reported counts, weights, loads and values must be
JSON integers (booleans and floating-point values are not integers). Empty
selections are feasible. Feasible suboptimal solutions remain valid; maximize
the independently recomputed total value. The quality objective is total_value,
with larger values better. There is no optimality hard constraint. Do not trust
or use a submitted summary as the authority for feasibility or quality. No
clarification or extra business assumptions are needed.
""".strip()

CASES = deepcopy(HISTORICAL_CASES)
for case in CASES.values():
    prefix, marker, _ = case["goal"].partition("Use only Python's standard library.")
    if not marker:
        raise ValueError("historical_goal_boundary_changed")
    case["goal"] = prefix + COMMON_GOAL
