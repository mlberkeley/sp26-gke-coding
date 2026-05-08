"""Run the local agent on a slice of QuixBugs and report pass rate.

Usage:
    GOOGLE_API_KEY=... pixi run python benchmarks/run_benchmark.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmarks.loader import load_quixbugs, quixbugs_problems
from benchmarks.local_agent import fix_with_agent


def main() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("GOOGLE_API_KEY not set in env.", file=sys.stderr)
        print(
            "Try: export GOOGLE_API_KEY=$(kubectl get secret google-api-key "
            "-o jsonpath='{.data.GOOGLE_API_KEY}' | base64 -d)",
            file=sys.stderr,
        )
        sys.exit(1)

    problems = quixbugs_problems()
    print(f"Running {len(problems)} QuixBugs problems with local agent\n")

    results: list[dict] = []
    t_total = time.time()

    for i, pid in enumerate(problems, 1):
        print(f"[{i}/{len(problems)}] {pid:30s} ", end="", flush=True)
        try:
            problem_id, buggy, test_code = load_quixbugs(pid)
            t0 = time.time()
            result = fix_with_agent(problem_id, buggy, test_code)
            elapsed = time.time() - t0
            num_attempts = len(result.attempts)
            print(
                f"{result.final_status.upper():25s} "
                f"({num_attempts} attempts, {elapsed:.1f}s)"
            )
            results.append(
                {
                    "problem_id": pid,
                    "status": result.final_status,
                    "attempts": num_attempts,
                    "elapsed_s": round(elapsed, 1),
                    "iron_curtain_rejections": sum(
                        1 for a in result.attempts if a.status == "iron_curtain_rejected"
                    ),
                }
            )
        except Exception as e:
            print(f"DRIVER ERROR: {type(e).__name__}: {e}")
            results.append(
                {
                    "problem_id": pid,
                    "status": "driver_error",
                    "attempts": 0,
                    "elapsed_s": 0,
                    "iron_curtain_rejections": 0,
                }
            )

    total_elapsed = time.time() - t_total

    passed = sum(1 for r in results if r["status"] in ("passed", "passed_without_fix"))
    failed = sum(1 for r in results if r["status"] == "failed")
    errors = sum(1 for r in results if r["status"] == "driver_error")

    print(f"\n=== Summary  (total {total_elapsed:.1f}s) ===")
    print(f"  Passed: {passed}/{len(results)}")
    print(f"  Failed: {failed}/{len(results)}")
    if errors:
        print(f"  Driver errors: {errors}/{len(results)}")
    print()
    for r in results:
        marker = "PASS" if r["status"] in ("passed", "passed_without_fix") else "FAIL"
        print(
            f"  [{marker}] {r['problem_id']:30s} "
            f"{r['status']:22s} "
            f"{r['attempts']} attempts, "
            f"{r['elapsed_s']}s"
        )

    out_csv = REPO_ROOT / "benchmarks" / "results.csv"
    with open(out_csv, "w") as f:
        f.write("problem_id,status,attempts,elapsed_s,iron_curtain_rejections\n")
        for r in results:
            f.write(
                f"{r['problem_id']},{r['status']},{r['attempts']},"
                f"{r['elapsed_s']},{r['iron_curtain_rejections']}\n"
            )
    print(f"\nResults: {out_csv}")

    out_json = REPO_ROOT / "benchmarks" / "results.json"
    out_json.write_text(json.dumps(results, indent=2))
    print(f"Results: {out_json}")


if __name__ == "__main__":
    main()
