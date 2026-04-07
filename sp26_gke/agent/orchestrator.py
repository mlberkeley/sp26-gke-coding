"""Orchestrator: LLM-driven tool-use loop for dynamic sub-agent coordination.

The orchestrator accumulates a full history of every action taken and result
seen, then asks the LLM what to do next.  It can invoke any sub-agent any
number of times in any order and decides autonomously when to accept a fix or
give up — based on accumulated evidence, not a fixed retry counter.

Inter-agent communication: ConfigMaps carry input into each GKE Job; the
orchestrator extracts results from pod logs and keeps them as typed Python
objects in its own process.  No additional shared storage is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
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
_MAX_STEPS = 10  # hard ceiling on total tool calls; prevents runaway cost

_DIAGNOSER_CMD = ["python", "/app/sp26_gke/workflows/diagnoser_job.py"]
_FIXER_CMD = ["python", "/app/sp26_gke/workflows/fixer_job.py"]
_REVIEWER_CMD = ["python", "/app/sp26_gke/workflows/reviewer_job.py"]

_VALID_ACTIONS = {"diagnose", "fix", "review", "accept", "give_up"}


@dataclass
class DiagnoseResult:
    diagnosis: str


@dataclass
class FixResult:
    fixed_code: str
    sandbox_result: str
    sandbox_passed: bool


@dataclass
class ReviewResult:
    decision: str
    reviewer_passed: bool
    approved: bool


@dataclass
class HistoryEntry:
    step: int
    action: str
    result: DiagnoseResult | FixResult | ReviewResult


def _latest_diagnosis(history: list[HistoryEntry]) -> str | None:
    for entry in reversed(history):
        if entry.action == "diagnose" and isinstance(entry.result, DiagnoseResult):
            return entry.result.diagnosis
    return None


def _latest_fix_result(history: list[HistoryEntry]) -> FixResult | None:
    for entry in reversed(history):
        if entry.action == "fix" and isinstance(entry.result, FixResult):
            return entry.result
    return None


def _latest_review_result(history: list[HistoryEntry]) -> ReviewResult | None:
    for entry in reversed(history):
        if entry.action == "review" and isinstance(entry.result, ReviewResult):
            return entry.result
    return None


def _run_diagnoser(code: str, failure_context: str | None) -> DiagnoseResult:
    input_data: dict[str, str] = {"buggy_script.py": code}
    if failure_context:
        input_data["failure_context.txt"] = failure_context
    job, cm = spawn_job(
        "diagnoser", input_data, _DIAGNOSER_CMD, needs_google_api_key=True
    )
    logs = wait_for_logs(job)
    print(f"[Diagnoser logs]\n{logs}")
    diagnosis = parse_output(logs)
    cleanup_job(job, cm)
    return DiagnoseResult(diagnosis=diagnosis)


def _run_fixer(code: str, diagnosis: str) -> FixResult:
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
    passed = (
        "Traceback" not in sandbox_result and "AssertionError" not in sandbox_result
    )
    return FixResult(
        fixed_code=fixed, sandbox_result=sandbox_result, sandbox_passed=passed
    )


def _run_reviewer(original: str, fixed: str, fixer_sandbox_result: str) -> ReviewResult:
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
    approved = "APPROVED" in decision.upper()
    cleanup_job(job, cm)
    return ReviewResult(
        decision=decision, reviewer_passed=reviewer_passed, approved=approved
    )


def _build_failure_context(history: list[HistoryEntry]) -> str | None:
    """
    Summarise all previous fix attempts into context for the next diagnoser call.

    Returns None when no fix attempts have been made yet (first diagnosis).
    """
    if not any(e.action in ("fix", "review") for e in history):
        return None

    lines = ["Previous fix attempts that failed:"]
    attempt = 0
    for entry in history:
        if entry.action == "diagnose" and isinstance(entry.result, DiagnoseResult):
            attempt += 1
            lines.append(f"\nAttempt {attempt} diagnosis: {entry.result.diagnosis}")
        elif entry.action == "fix" and isinstance(entry.result, FixResult):
            fix = entry.result
            lines.append(
                f"  Fixer sandbox: {'PASSED' if fix.sandbox_passed else 'FAILED'}"
            )
            if not fix.sandbox_passed:
                lines.append(f"  Error: {fix.sandbox_result[:300]}")
        elif entry.action == "review" and isinstance(entry.result, ReviewResult):
            rev = entry.result
            lines.append(f"  Review decision: {rev.decision[:200]}")
            lines.append(
                f"  Reviewer sandbox: {'PASSED' if rev.reviewer_passed else 'FAILED'}"
            )
    return "\n".join(lines)


def _format_history(history: list[HistoryEntry]) -> str:
    if not history:
        return "No actions taken yet."
    lines = []
    for entry in history:
        lines.append(f"Step {entry.step}: {entry.action.upper()}")
        if entry.action == "diagnose" and isinstance(entry.result, DiagnoseResult):
            lines.append(f"  Diagnosis: {entry.result.diagnosis[:250]}")
        elif entry.action == "fix" and isinstance(entry.result, FixResult):
            fix = entry.result
            lines.append(
                f"  Fixer sandbox: {'PASSED' if fix.sandbox_passed else 'FAILED'}"
            )
            if not fix.sandbox_passed:
                lines.append(f"  Failure: {fix.sandbox_result[:250]}")
        elif entry.action == "review" and isinstance(entry.result, ReviewResult):
            rev = entry.result
            lines.append(f"  Decision: {rev.decision[:200]}")
            lines.append(
                f"  Reviewer sandbox: {'PASSED' if rev.reviewer_passed else 'FAILED'}"
            )
    return "\n".join(lines)


def _next_action(
    llm: ChatGoogleGenerativeAI,
    original_code: str,
    history: list[HistoryEntry],
    steps_remaining: int,
) -> tuple[str, str]:
    """
    Ask the LLM what to do next given accumulated history.

    Returns (action, reason) where action is one of the _VALID_ACTIONS.
    """
    latest_diagnosis = _latest_diagnosis(history)
    latest_fix = _latest_fix_result(history)
    latest_review = _latest_review_result(history)

    state_lines = [f"Latest diagnosis: {latest_diagnosis or 'none yet'}"]
    if latest_fix:
        state_lines.append(
            f"Latest fix sandbox: {'PASSED' if latest_fix.sandbox_passed else 'FAILED'}"
        )
    else:
        state_lines.append("Latest fix: none yet")
    if latest_review:
        state_lines.append(f"Latest review: {latest_review.decision[:150]}")
        state_lines.append(
            f"Latest reviewer sandbox: {'PASSED' if latest_review.reviewer_passed else 'FAILED'}"
        )
    else:
        state_lines.append("Latest review: none yet")

    prompt = f"""You are orchestrating a code-fixing pipeline. Choose the next action.

TOOLS:
- diagnose  Run the diagnoser agent to identify the bug
- fix       Run the fixer agent and gVisor sandbox verification (requires a prior diagnosis)
- review    Run the reviewer agent and independent gVisor sandbox (requires a prior fix)
- accept    The fix is verified correct — finish successfully
- give_up   The fix cannot be found — finish with failure

ORIGINAL BUGGY CODE:
{original_code}

HISTORY:
{_format_history(history)}

CURRENT STATE:
{chr(10).join(state_lines)}

Steps remaining before forced termination: {steps_remaining}

Rules:
- Always diagnose before fixing.
- Always review after fixing.
- Only accept if the latest review approved AND both sandboxes passed.
- If a fix was rejected or sandbox failed, diagnose again before fixing again.
- Give up if the same approach has failed multiple times with no better strategy apparent.

Reply in exactly this format:
ACTION: <diagnose|fix|review|accept|give_up>
REASON: <one sentence>"""

    response = llm.invoke(prompt)
    content = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    action = "give_up"
    reason = ""
    for line in content.splitlines():
        if line.startswith("ACTION:"):
            action = line.split(":", 1)[1].strip().lower()
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    if action not in _VALID_ACTIONS:
        action = "give_up"

    return action, reason


def run_orchestrator() -> None:
    """
    Run the dynamic fix loop.

    The orchestrator LLM reads the full history of all sub-agent results at each step
    and decides which sub-agent to spawn next.  It controls ordering, repetition, and
    termination — there is no fixed attempt counter.  A hard step ceiling of _MAX_STEPS
    prevents runaway cost.
    """
    config.load_kube_config(config_file=_KUBECONFIG)

    original_code = Path("/input/buggy_script.py").read_text()
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    history: list[HistoryEntry] = []
    fixed_code = original_code
    step = 0

    while step < _MAX_STEPS:
        step += 1
        action, reason = _next_action(llm, original_code, history, _MAX_STEPS - step)
        print(f"\n[Orchestrator] Step {step}: {action.upper()} — {reason}")

        if action == "accept":
            print("\n--- AGENT STATUS: PASSED ---")
            print("--- FINAL CODE START ---")
            print(fixed_code)
            print("--- FINAL CODE END ---")
            return

        if action == "give_up":
            break

        if action == "diagnose":
            failure_context = _build_failure_context(history)
            diag = _run_diagnoser(original_code, failure_context)
            history.append(HistoryEntry(step=step, action="diagnose", result=diag))
            print(f"[Orchestrator] Diagnosis: {diag.diagnosis[:300]}")

        elif action == "fix":
            latest_diagnosis = _latest_diagnosis(history)
            if not latest_diagnosis:
                print(
                    "[Orchestrator] LLM requested fix without a diagnosis — stopping."
                )
                break
            fix = _run_fixer(original_code, latest_diagnosis)
            history.append(HistoryEntry(step=step, action="fix", result=fix))
            if fix.fixed_code:
                fixed_code = fix.fixed_code
            print(
                f"[Orchestrator] Fixer sandbox: {'PASSED' if fix.sandbox_passed else 'FAILED'}"
            )

        elif action == "review":
            latest_fix = _latest_fix_result(history)
            if not latest_fix or not latest_fix.fixed_code:
                print("[Orchestrator] LLM requested review without a fix — stopping.")
                break
            review = _run_reviewer(
                original_code, latest_fix.fixed_code, latest_fix.sandbox_result
            )
            history.append(HistoryEntry(step=step, action="review", result=review))
            print(
                f"[Orchestrator] Reviewer sandbox: {'PASSED' if review.reviewer_passed else 'FAILED'} | "
                f"Decision: {review.decision[:150]}"
            )

    print("\n--- AGENT STATUS: FAILED ---")
    print("--- FINAL CODE START ---")
    print(fixed_code)
    print("--- FINAL CODE END ---")
