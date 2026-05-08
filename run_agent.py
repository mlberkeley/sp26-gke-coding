"""
Submit a Python file to the coding agent and stream results to the terminal.

Usage:
    python run_agent.py <file.py>
    python run_agent.py sp26_gke/tests/buggy_script.py
"""

import difflib
import sys
from pathlib import Path

from ui.k8s_client import cleanup, stream_logs, submit


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python run_agent.py <file.py>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    original = path.read_text()

    print(f"Submitting {path.name} to coding agent...")
    job_name, cm_name = submit(original)
    print(f"Job: {job_name}")
    print("─" * 60)

    final_lines: list[str] = []
    sentinel_reason_lines: list[str] = []
    capturing_code = False
    capturing_reason = False
    agent_status = None

    try:
        for line in stream_logs(job_name):
            if "--- AGENT STATUS: PASSED ---" in line:
                agent_status = "PASSED"
            elif "--- AGENT STATUS: FAILED ---" in line:
                agent_status = "FAILED"
            elif "--- AGENT STATUS: REJECTED ---" in line:
                agent_status = "REJECTED"
            elif "--- FINAL CODE START ---" in line:
                capturing_code = True
            elif "--- FINAL CODE END ---" in line:
                capturing_code = False
            elif "--- SENTINEL REASON START ---" in line:
                capturing_reason = True
            elif "--- SENTINEL REASON END ---" in line:
                capturing_reason = False
            elif capturing_code:
                final_lines.append(line)
            elif capturing_reason:
                sentinel_reason_lines.append(line)
            else:
                print(line)
    finally:
        cleanup(job_name, cm_name)

    print("─" * 60)

    fixed = "\n".join(final_lines)

    if agent_status == "REJECTED":
        print("🛑  REJECTED — sentinel flagged the input as a suspected prompt injection")
        if sentinel_reason_lines:
            print(f"    reason: {' '.join(sentinel_reason_lines).strip()}")
        return
    if agent_status == "PASSED":
        print("✅  PASSED — agent fixed the code")
    else:
        print("⚠️   FAILED — max retries reached, showing best attempt")

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="original",
            tofile="fixed",
        )
    )

    if diff:
        print("\n--- diff ---")
        print(diff)

    print("\n--- fixed code ---")
    print(fixed)


if __name__ == "__main__":
    main()
