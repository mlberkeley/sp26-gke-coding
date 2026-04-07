"""Orchestrator: coordinates diagnoser, fixer, and reviewer sub-agent jobs.

Each agent spawns its own sandbox when needed:
- Fixer: verifies its fix before returning
- Reviewer: independently re-runs tests before approving
"""

from pathlib import Path

from kubernetes import config  # type: ignore[import-untyped]

from sp26_gke.agent.job_runner import (
    cleanup_job,
    parse_output,
    parse_section,
    spawn_job,
    wait_for_logs,
)

_KUBECONFIG = "/kubeconfig/config"
_MAX_RETRIES = 3

_DIAGNOSER_CMD = ["python", "/app/sp26_gke/workflows/diagnoser_job.py"]
_FIXER_CMD = ["python", "/app/sp26_gke/workflows/fixer_job.py"]
_REVIEWER_CMD = ["python", "/app/sp26_gke/workflows/reviewer_job.py"]


def _run_diagnoser(code: str) -> str:
    job, cm = spawn_job(
        "diagnoser",
        {"buggy_script.py": code},
        _DIAGNOSER_CMD,
        needs_google_api_key=True,
    )
    logs = wait_for_logs(job)
    print(f"[Diagnoser logs]\n{logs}")
    diagnosis = parse_output(logs)
    cleanup_job(job, cm)
    return diagnosis


def _run_fixer(code: str, diagnosis: str) -> tuple[str, str]:
    """Returns (fixed_code, sandbox_result)."""
    job, cm = spawn_job(
        "fixer",
        {"buggy_script.py": code, "diagnosis.txt": diagnosis},
        _FIXER_CMD,
        needs_kubeconfig=True,
        needs_google_api_key=True,
    )
    logs = wait_for_logs(job)
    print(f"[Fixer logs]\n{logs}")
    fixed = parse_section(logs, "--- FIXED CODE START ---", "--- FIXED CODE END ---")
    sandbox_result = parse_section(
        logs, "--- SANDBOX RESULT START ---", "--- SANDBOX RESULT END ---"
    )
    cleanup_job(job, cm)
    return fixed, sandbox_result


def _run_reviewer(
    original: str, fixed: str, fixer_sandbox_result: str
) -> tuple[str, bool]:
    """Returns (decision, reviewer_sandbox_passed)."""
    job, cm = spawn_job(
        "reviewer",
        {
            "original.py": original,
            "fixed.py": fixed,
            "fixer_sandbox_result.txt": fixer_sandbox_result,
        },
        _REVIEWER_CMD,
        needs_kubeconfig=True,
        needs_google_api_key=True,
    )
    logs = wait_for_logs(job)
    print(f"[Reviewer logs]\n{logs}")
    decision = parse_output(logs)
    reviewer_passed = "--- REVIEWER SANDBOX PASSED ---" in logs
    cleanup_job(job, cm)
    return decision, reviewer_passed


def run_orchestrator() -> None:
    """Run the full multiagent fix loop: diagnose → fix (with sandbox) → review (with sandbox)."""
    config.load_kube_config(config_file=_KUBECONFIG)

    original_code = Path("/input/buggy_script.py").read_text()
    current_code = original_code
    fixed_code = original_code

    for attempt in range(1, _MAX_RETRIES + 1):
        print(f"\n[Orchestrator] === Attempt {attempt}/{_MAX_RETRIES} ===")

        diagnosis = _run_diagnoser(current_code)
        print(f"[Orchestrator] Diagnosis: {diagnosis[:300]}")

        fixed_code, fixer_sandbox_result = _run_fixer(current_code, diagnosis)
        if not fixed_code:
            print("[Orchestrator] Fixer returned empty output, skipping attempt")
            continue

        fixer_passed = (
            "Traceback" not in fixer_sandbox_result
            and "AssertionError" not in fixer_sandbox_result
        )

        review_decision, reviewer_passed = _run_reviewer(
            original_code, fixed_code, fixer_sandbox_result
        )
        approved = "APPROVED" in review_decision.upper()

        print(
            f"[Orchestrator] Fixer sandbox: {'PASSED' if fixer_passed else 'FAILED'} | "
            f"Reviewer sandbox: {'PASSED' if reviewer_passed else 'FAILED'} | "
            f"Decision: {review_decision[:150]}"
        )

        if fixer_passed and reviewer_passed and approved:
            print("\n--- AGENT STATUS: PASSED ---")
            print("--- FINAL CODE START ---")
            print(fixed_code)
            print("--- FINAL CODE END ---")
            return

        current_code = fixed_code

    print("\n--- AGENT STATUS: FAILED ---")
    print("--- FINAL CODE START ---")
    print(fixed_code)
    print("--- FINAL CODE END ---")
