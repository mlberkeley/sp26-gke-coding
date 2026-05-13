"""
Evaluate the coding agent on QuixBugs benchmark problems.

Downloads buggy Python programs and JSON test cases from the QuixBugs GitHub
repo, generates a standalone test script for each problem, then runs the
full orchestrator pipeline (diagnose → fix → review) on GKE.

Usage:
    python eval/quixbugs_eval.py [--programs bitcount gcd ...]

Results are written to eval_results.json in the working directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from kubernetes import config as k8s_config  # type: ignore[import-untyped]

# Allow running as a top-level script from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sp26_gke.agent.job_runner import cleanup_job, spawn_job, wait_for_logs

# ---------------------------------------------------------------------------
# QuixBugs config
# ---------------------------------------------------------------------------

GITHUB_RAW = "https://raw.githubusercontent.com/jkoppel/QuixBugs/master"

# Curated subset: standalone programs whose inputs/outputs fit cleanly in JSON.
# Programs that require graph helper classes (Node, Graph) are excluded.
DEFAULT_PROGRAMS = [
    "bitcount",
    "bucketsort",
    "flatten",
    "gcd",
    "get_factors",
    "hanoi",
    "is_valid_parenthesization",
    "levenshtein",
    "longest_common_subsequence",
    "longest_increasing_subsequence",
    "max_sublist_sum",
    "mergesort",
    "next_palindrome",
    "next_permutation",
    "pascal",
    "powerset",
    "rpn_eval",
    "shunting_yard",
    "sieve",
    "sqrt",
    "wrap",
]

_ORCHESTRATOR_CMD = ["python", "/app/sp26_gke/workflows/orchestrator_job.py"]

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch(url: str) -> str | None:
    """GET a URL and return the body text, or None on any failure."""
    try:
        r = requests.get(url, timeout=30)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def fetch_program(name: str) -> str | None:
    return _fetch(f"{GITHUB_RAW}/python_programs/{name}.py")


def fetch_test_cases(name: str) -> list | None:
    """
    Fetch and parse QuixBugs JSON test cases.

    Each line is a standalone JSON value [[inputs...], expected],
    NOT a single top-level JSON array.
    """
    raw = _fetch(f"{GITHUB_RAW}/json_testcases/{name}.json")
    if raw is None:
        return None
    cases = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return cases if cases else None


# ---------------------------------------------------------------------------
# Test script generation
# ---------------------------------------------------------------------------


def generate_test_script(func_name: str, test_cases: list) -> str:
    """
    Build a self-contained Python test script from QuixBugs JSON test cases.

    JSON format:  [ [[arg1, arg2, ...], expected], ... ]

    The script imports func_name from buggy_script, runs every test case, and
    prints "PASSED: test_<func>" on success.  Generator results are converted
    to list before comparison so they match the JSON expected values.
    """
    # Embed test data as a Python literal directly in the script — no file I/O
    # needed inside the sandbox.
    test_data_repr = json.dumps(test_cases, indent=4)

    lines = [
        f'"""Auto-generated QuixBugs test for: {func_name}"""',
        "",
        "import types",
        f"from buggy_script import {func_name}",
        "",
        "",
        "def _to_comparable(val):",
        "    if isinstance(val, types.GeneratorType):",
        "        return list(val)",
        "    return val",
        "",
        "",
        f"def test_{func_name}():",
        f"    test_cases = {test_data_repr}",
        "    for inputs, expected in test_cases:",
        f"        result = _to_comparable({func_name}(*inputs))",
        "        assert result == expected, (",
        f'            f"{func_name}({{inputs!r}}) → {{result!r}}, expected {{expected!r}}"',
        "        )",
        f'    print("PASSED: test_{func_name}")',
        "",
        "",
        'if __name__ == "__main__":',
        f'    print("Running tests for {func_name}")',
        f"    test_{func_name}()",
        '    print("All tests executed.")',
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    program: str
    status: str  # "passed" | "failed" | "error"
    steps: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Running one problem
# ---------------------------------------------------------------------------


def run_problem(func_name: str, buggy_code: str, test_script: str) -> EvalResult:
    """Spawn an orchestrator GKE job for one problem and parse the outcome."""
    try:
        job, cm = spawn_job(
            "orchestrator",
            {"buggy_script.py": buggy_code, "test_script.py": test_script},
            _ORCHESTRATOR_CMD,
            needs_kubeconfig=True,
            needs_google_api_key=True,
        )
        logs = wait_for_logs(job)
        cleanup_job(job, cm)

        passed = "--- AGENT STATUS: PASSED ---" in logs
        failed = "--- AGENT STATUS: FAILED ---" in logs
        steps = logs.count("[Orchestrator] Step ")
        status = "passed" if passed else ("failed" if failed else "error")
        return EvalResult(program=func_name, status=status, steps=steps)

    except Exception as exc:
        return EvalResult(program=func_name, status="error", error=str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(programs: list[str]) -> None:
    k8s_config.load_kube_config()

    results: list[EvalResult] = []

    for func_name in programs:
        print(f"\n{'=' * 60}")
        print(f"Evaluating: {func_name}")
        print(f"{'=' * 60}")

        buggy_code = fetch_program(func_name)
        if buggy_code is None:
            print(f"  SKIP: could not fetch {func_name}.py from GitHub")
            results.append(EvalResult(func_name, "error", error="fetch failed"))
            continue

        test_cases = fetch_test_cases(func_name)
        if test_cases is None:
            print(f"  SKIP: could not fetch {func_name}.json from GitHub")
            results.append(EvalResult(func_name, "error", error="no test cases"))
            continue

        print(f"  Buggy code: {len(buggy_code)} chars | Test cases: {len(test_cases)}")
        test_script = generate_test_script(func_name, test_cases)

        result = run_problem(func_name, buggy_code, test_script)
        results.append(result)
        print(f"  Result: {result.status.upper()} ({result.steps} orchestrator steps)")

        # Pause between problems to avoid overwhelming the cluster.
        time.sleep(5)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    passed = [r for r in results if r.status == "passed"]
    failed = [r for r in results if r.status == "failed"]
    errors = [r for r in results if r.status == "error"]

    print(f"\n{'=' * 60}")
    print("EVALUATION SUMMARY")
    print(f"{'=' * 60}")
    total = len(results)
    rate = len(passed) / total * 100 if total else 0.0
    print(
        f"Total: {total}  |  Passed: {len(passed)}  |  Failed: {len(failed)}  |  Error: {len(errors)}"
    )
    print(f"Pass rate: {rate:.1f}%")

    if passed:
        print("\nPASSED:")
        for r in passed:
            print(f"  + {r.program} ({r.steps} steps)")
    if failed:
        print("\nFAILED:")
        for r in failed:
            print(f"  - {r.program} ({r.steps} steps)")
    if errors:
        print("\nERRORS:")
        for r in errors:
            print(f"  ! {r.program}: {r.error}")

    output = {
        "summary": {
            "total": total,
            "passed": len(passed),
            "failed": len(failed),
            "error": len(errors),
            "pass_rate": rate,
        },
        "results": [
            {
                "program": r.program,
                "status": r.status,
                "steps": r.steps,
                "error": r.error,
            }
            for r in results
        ],
    }
    # Always write next to this script, regardless of cwd.
    out_path = Path(__file__).parent / "eval_results.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate agent on QuixBugs")
    parser.add_argument(
        "--programs",
        nargs="+",
        default=DEFAULT_PROGRAMS,
        metavar="NAME",
        help="QuixBugs program names to evaluate (default: curated subset of 21)",
    )
    args = parser.parse_args()
    main(args.programs)
