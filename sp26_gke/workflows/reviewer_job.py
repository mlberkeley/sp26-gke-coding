"""Reviewer sub-agent: independently re-runs tests and approves or rejects the fix."""

from pathlib import Path

from kubernetes import config  # type: ignore[import-untyped]
from langchain_google_genai import ChatGoogleGenerativeAI

from sp26_gke.agent.job_runner import cleanup_job, spawn_job, wait_for_logs

_KUBECONFIG = "/kubeconfig/config"
# If /input/test_script.py is present in the sandbox ConfigMap, use it.
# Otherwise fall back to the test suite baked into the image.
_SANDBOX_CMD = [
    "sh",
    "-c",
    (
        "cp /input/buggy_script.py /workspace/buggy_script.py && "
        "if [ -f /input/test_script.py ]; then "
        "  cp /input/test_script.py /workspace/test_buggy_script.py; "
        "else "
        "  cp /app/sp26_gke/tests/test_buggy_script.py /workspace/test_buggy_script.py; "
        "fi && "
        "cd /workspace && python -u test_buggy_script.py"
    ),
]


def _run_sandbox(fixed_code: str, test_script: str | None = None) -> str:
    input_data: dict[str, str] = {"buggy_script.py": fixed_code}
    if test_script:
        input_data["test_script.py"] = test_script
    job, cm = spawn_job("sandbox", input_data, _SANDBOX_CMD, use_gvisor=True)
    logs = wait_for_logs(job)
    cleanup_job(job, cm)
    return logs


def main() -> None:
    config.load_kube_config(config_file=_KUBECONFIG)

    original = Path("/input/original.py").read_text()
    fixed = Path("/input/fixed.py").read_text()
    fixer_sandbox_result = Path("/input/fixer_sandbox_result.txt").read_text()
    test_script_path = Path("/input/test_script.py")
    test_script = test_script_path.read_text() if test_script_path.exists() else None
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    print("[Reviewer] Running independent sandbox verification...")
    reviewer_sandbox_result = _run_sandbox(fixed, test_script)
    print(f"[Reviewer] Independent sandbox result:\n{reviewer_sandbox_result}")

    passed = (
        "Traceback" not in reviewer_sandbox_result
        and "AssertionError" not in reviewer_sandbox_result
    )

    prompt = f"""Review this Python code fix.

ORIGINAL (buggy):
{original}

FIXED:
{fixed}

FIXER'S TEST OUTPUT:
{fixer_sandbox_result}

YOUR INDEPENDENT TEST OUTPUT:
{reviewer_sandbox_result}

Does the fix correctly address the bug and is the code logically sound?
Start your response with exactly APPROVED or REJECTED, then give a one-sentence reason.
"""
    response = llm.invoke(prompt)
    content = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    print("--- AGENT OUTPUT START ---")
    print(content)
    print("--- AGENT OUTPUT END ---")
    print(
        "--- REVIEWER SANDBOX PASSED ---"
        if passed
        else "--- REVIEWER SANDBOX FAILED ---"
    )


if __name__ == "__main__":
    main()
