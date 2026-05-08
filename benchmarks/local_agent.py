"""Local agent that mirrors the GKE orchestrator's diagnose-fix-review loop.

Calls Gemini directly (no K8s Jobs), runs candidate fixes via subprocess
(no gVisor).  Reuses the iron-curtain policy module verbatim so the static
analysis layer stays consistent with the production pipeline.

Used by run_benchmark.py to score how well the agent fixes external benchmark
problems (QuixBugs, etc.) without paying GKE per-Job overhead.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI

from sp26_gke.agent.llm_text import extract_text
from sp26_gke.agent.policy import format_violations, is_approved

_MODEL = "gemini-3-flash-preview"
_MAX_ATTEMPTS = 3
_SUBPROCESS_TIMEOUT_S = 15


@dataclass
class Attempt:
    diagnosis: str
    fix: str
    status: str  # "passed" | "failed" | "iron_curtain_rejected" | "subprocess_error"
    output: str


@dataclass
class RunResult:
    problem_id: str
    final_status: str
    attempts: list[Attempt]
    final_code: str | None
    initial_failure: str


def _run_in_subprocess(problem_id: str, code: str, test_code: str) -> tuple[int, str]:
    """Write code as `<problem_id>.py` and test_code as `_test.py` in a tmp dir; run."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / f"{problem_id}.py").write_text(code)
        test_file = td_path / "_test.py"
        test_file.write_text(test_code)
        try:
            result = subprocess.run(
                [sys.executable, str(test_file)],
                cwd=td_path,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_S,
            )
            return result.returncode, (result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            return 124, f"TIMEOUT after {_SUBPROCESS_TIMEOUT_S}s"


def _diagnose(
    llm: ChatGoogleGenerativeAI,
    code: str,
    failure: str,
    prior: list[str],
) -> str:
    prior_block = ""
    if prior:
        prior_block = "\nPRIOR FAILED ATTEMPTS:\n" + "\n".join(prior)
    prompt = f"""Analyze this Python code and identify the bug.

CODE:
{code}

TEST FAILURE:
{failure}
{prior_block}

Provide a concise diagnosis: what is wrong, what type of bug it is, and what the high-level fix is.  Keep it under 3 sentences."""
    return extract_text(llm.invoke(prompt)).strip()


def _propose_fix(llm: ChatGoogleGenerativeAI, code: str, diagnosis: str) -> str:
    prompt = f"""Fix this Python code based on the diagnosis below.

CODE:
{code}

DIAGNOSIS:
{diagnosis}

Return ONLY the corrected Python code.  No explanation, no markdown fences.  Just raw Python."""
    raw = extract_text(llm.invoke(prompt))
    return raw.replace("```python", "").replace("```", "").strip()


def fix_with_agent(
    problem_id: str,
    buggy_code: str,
    test_code: str,
    *,
    enforce_iron_curtain: bool = True,
) -> RunResult:
    """Run the diagnose→fix→sandbox loop locally; return aggregated result."""
    llm = ChatGoogleGenerativeAI(model=_MODEL, temperature=0)

    rc, initial_output = _run_in_subprocess(problem_id, buggy_code, test_code)
    if rc == 0:
        return RunResult(
            problem_id=problem_id,
            final_status="passed_without_fix",
            attempts=[],
            final_code=buggy_code,
            initial_failure="(buggy code already passes — nothing to fix)",
        )

    attempts: list[Attempt] = []
    prior_summaries: list[str] = []
    failure = initial_output

    for attempt_num in range(1, _MAX_ATTEMPTS + 1):
        diagnosis = _diagnose(llm, buggy_code, failure, prior_summaries)
        fix = _propose_fix(llm, buggy_code, diagnosis)

        if enforce_iron_curtain:
            approved, violations = is_approved(fix)
            if not approved:
                detail = format_violations(violations)
                attempts.append(
                    Attempt(
                        diagnosis=diagnosis,
                        fix=fix,
                        status="iron_curtain_rejected",
                        output=detail,
                    )
                )
                prior_summaries.append(
                    f"Attempt {attempt_num}: iron-curtain rejected the fix ({detail.splitlines()[0]})"
                )
                continue

        rc, output = _run_in_subprocess(problem_id, fix, test_code)
        status = "passed" if rc == 0 else "failed"
        attempts.append(
            Attempt(diagnosis=diagnosis, fix=fix, status=status, output=output)
        )

        if status == "passed":
            return RunResult(
                problem_id=problem_id,
                final_status="passed",
                attempts=attempts,
                final_code=fix,
                initial_failure=initial_output,
            )

        prior_summaries.append(
            f"Attempt {attempt_num} diagnosis: {diagnosis[:200]}\n  Result: {output[:300]}"
        )
        failure = output

    return RunResult(
        problem_id=problem_id,
        final_status="failed",
        attempts=attempts,
        final_code=attempts[-1].fix if attempts else None,
        initial_failure=initial_output,
    )
