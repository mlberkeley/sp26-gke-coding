"""Load benchmark problems into (problem_id, buggy_code, test_code) triples.

Currently supports QuixBugs (jkoppel/QuixBugs).  Each problem yields a
self-contained Python test runner that imports the candidate, drives the
benchmark's JSON test cases, and exits 0 on full pass / nonzero on any failure.
"""

from __future__ import annotations

import json
from pathlib import Path

QUIXBUGS_ROOT = Path("/tmp/QuixBugs")

# A representative slice covering operator flips, recursion, sort, search, DP.
QUIXBUGS_DEFAULT_PROBLEMS = [
    "bitcount",
    "gcd",
    "find_first_in_sorted",
    "flatten",
    "hanoi",
    "kheapsort",
    "lcs_length",
    "mergesort",
    "sqrt",
    "next_palindrome",
]


def _quixbugs_test_runner(problem_id: str, json_testcases: list) -> str:
    """Return self-contained Python that imports the candidate and runs JSON cases."""
    cases_repr = json.dumps(json_testcases)
    return f'''
"""Auto-generated test runner for QuixBugs problem '{problem_id}'."""
import json
import sys

cases = json.loads({json.dumps(cases_repr)})
try:
    from {problem_id} import {problem_id}
except Exception as e:
    print(f"IMPORT_FAILED: {{type(e).__name__}}: {{e}}")
    sys.exit(1)

failures = 0
for input_data, expected in cases:
    try:
        if isinstance(input_data, list):
            result = {problem_id}(*input_data)
        else:
            result = {problem_id}(input_data)
        # Some problems return generators / iterators
        if hasattr(result, "__iter__") and not isinstance(
            result, (list, str, int, float, dict, set, tuple, bool)
        ):
            result = list(result)
        if result != expected:
            print(f"FAIL: input={{input_data!r}} expected={{expected!r}} got={{result!r}}")
            failures += 1
    except Exception as e:
        print(f"ERROR: input={{input_data!r}} -> {{type(e).__name__}}: {{e}}")
        failures += 1

if failures == 0:
    print(f"PASSED: all {{len(cases)}} cases")
    sys.exit(0)
print(f"FAILED: {{failures}}/{{len(cases)}} cases failed")
sys.exit(1)
'''


def load_quixbugs(problem_id: str) -> tuple[str, str, str]:
    """Return (problem_id, buggy_code, test_code) for one QuixBugs problem."""
    buggy_path = QUIXBUGS_ROOT / "python_programs" / f"{problem_id}.py"
    cases_path = QUIXBUGS_ROOT / "json_testcases" / f"{problem_id}.json"
    if not buggy_path.exists():
        raise FileNotFoundError(buggy_path)
    if not cases_path.exists():
        raise FileNotFoundError(cases_path)
    buggy = buggy_path.read_text()
    cases = [
        json.loads(line)
        for line in cases_path.read_text().splitlines()
        if line.strip()
    ]
    test_code = _quixbugs_test_runner(problem_id, cases)
    return problem_id, buggy, test_code


def quixbugs_problems() -> list[str]:
    return list(QUIXBUGS_DEFAULT_PROBLEMS)
