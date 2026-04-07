"""Orchestrator: LLM-driven coordination of diagnoser, fixer, and reviewer sub-agent jobs.

After each failed attempt the orchestrator asks an LLM to reason about what
went wrong and decide whether to retry (with a targeted hint for the next
diagnoser call), give up early, or accept the result.  This replaces the
previous fixed-counter retry loop.
"""

from pathlib import Path

from kubernetes import config  # type: ignore[import-untyped]
from langchain_google_genai import ChatGoogleGenerativeAI

from sp26_gke.agent.job_runner import (
    cleanup_job,
    parse_output,
    parse_section,
    spawn_job,
    wait_for_logs,
)

_KUBECONFIG = "/kubeconfig/config"
_MAX_ATTEMPTS = 3

_DIAGNOSER_CMD = ["python", "/app/sp26_gke/workflows/diagnoser_job.py"]
_FIXER_CMD = ["python", "/app/sp26_gke/workflows/fixer_job.py"]
_REVIEWER_CMD = ["python", "/app/sp26_gke/workflows/reviewer_job.py"]


def _run_diagnoser(code: str, failure_context: str | None = None) -> str:
    input_data: dict[str, str] = {"buggy_script.py": code}
    if failure_context:
        input_data["failure_context.txt"] = failure_context
    job, cm = spawn_job(
        "diagnoser",
        input_data,
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


def _decide_next_action(
    llm: ChatGoogleGenerativeAI,
    attempt: int,
    max_attempts: int,
    fixer_sandbox_passed: bool,
    reviewer_sandbox_passed: bool,
    review_decision: str,
    diagnosis: str,
    fixer_sandbox_result: str,
) -> tuple[str, str]:
    """
    Ask the LLM what to do after a failed attempt.

    Returns (action, hint) where action is ACCEPT, RETRY, or GIVE_UP and hint is a one-
    sentence context string for the next diagnoser call (empty when not retrying).
    """
    remaining = max_attempts - attempt
    prompt = f"""You are coordinating a code-fixing pipeline. An attempt just completed.

Attempt {attempt} of {max_attempts}:
- Fixer sandbox (fixed code vs tests): {"PASSED" if fixer_sandbox_passed else "FAILED"}
- Reviewer sandbox (independent run):  {"PASSED" if reviewer_sandbox_passed else "FAILED"}
- Reviewer decision: {review_decision}
- Diagnosis used:    {diagnosis}
- Fixer sandbox output (first 500 chars): {fixer_sandbox_result[:500]}

Remaining attempts: {remaining}

Reply in exactly this format:
ACTION: <ACCEPT|RETRY|GIVE_UP>
HINT: <one-sentence hint for the next diagnoser, or 'none'>

Rules:
- ACCEPT only if both sandboxes passed and reviewer approved.
- RETRY if attempts remain and the failure suggests a different approach could work.
- GIVE_UP if the fix is fundamentally wrong and further retries will not help,
  or if no attempts remain.
- When RETRY, write a specific hint saying what the previous diagnosis got wrong
  and what the next attempt should try instead."""

    response = llm.invoke(prompt)
    content = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    action = "GIVE_UP"
    hint = ""
    for line in content.splitlines():
        if line.startswith("ACTION:"):
            action = line.split(":", 1)[1].strip().upper()
        elif line.startswith("HINT:"):
            raw = line.split(":", 1)[1].strip()
            hint = "" if raw.lower() == "none" else raw

    if action not in ("ACCEPT", "RETRY", "GIVE_UP"):
        action = "GIVE_UP"

    return action, hint


def run_orchestrator() -> None:
    """
    Run the fix loop with LLM-driven retry decisions.

    On each failure the orchestrator LLM synthesises what went wrong and passes a
    targeted hint to the next diagnoser call, so each attempt tries a different strategy
    rather than repeating the same one.  The two gVisor sandbox verification steps
    (fixer and reviewer) are preserved on every attempt.
    """
    config.load_kube_config(config_file=_KUBECONFIG)

    original_code = Path("/input/buggy_script.py").read_text()
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    failure_context: str | None = None
    fixed_code = original_code

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        print(f"\n[Orchestrator] === Attempt {attempt}/{_MAX_ATTEMPTS} ===")

        diagnosis = _run_diagnoser(original_code, failure_context)
        print(f"[Orchestrator] Diagnosis: {diagnosis[:300]}")

        fixed_code, fixer_sandbox_result = _run_fixer(original_code, diagnosis)
        if not fixed_code:
            print(
                "[Orchestrator] Fixer returned empty output, treating as failed attempt"
            )
            failure_context = (
                f"Attempt {attempt}: fixer produced no code. Try a clearer diagnosis."
            )
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

        if attempt == _MAX_ATTEMPTS:
            break

        action, hint = _decide_next_action(
            llm,
            attempt,
            _MAX_ATTEMPTS,
            fixer_passed,
            reviewer_passed,
            review_decision,
            diagnosis,
            fixer_sandbox_result,
        )
        print(
            f"[Orchestrator] LLM decision: {action}"
            + (f" | Hint: {hint[:150]}" if hint else "")
        )

        if action == "ACCEPT":
            print("\n--- AGENT STATUS: PASSED ---")
            print("--- FINAL CODE START ---")
            print(fixed_code)
            print("--- FINAL CODE END ---")
            return

        if action == "GIVE_UP":
            print("[Orchestrator] LLM decided to give up.")
            break

        # RETRY: build failure context for the next diagnoser call
        failure_context = (
            f"Attempt {attempt} failed.\n"
            f"Diagnosis tried: {diagnosis}\n"
            f"Fixer sandbox: {'PASSED' if fixer_passed else 'FAILED'}\n"
            f"Reviewer decision: {review_decision}\n"
            f"What to try differently: {hint}"
        )

    print("\n--- AGENT STATUS: FAILED ---")
    print("--- FINAL CODE START ---")
    print(fixed_code)
    print("--- FINAL CODE END ---")
