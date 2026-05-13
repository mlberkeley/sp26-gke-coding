"""Fixer sub-agent: generates corrected code and verifies it in a sandbox."""

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

    code = Path("/input/buggy_script.py").read_text()
    diagnosis = Path("/input/diagnosis.txt").read_text()
    test_script_path = Path("/input/test_script.py")
    test_script = test_script_path.read_text() if test_script_path.exists() else None
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    prompt = f"""Fix this Python code based on the diagnosis below.

CODE:
{code}

DIAGNOSIS:
{diagnosis}

Return ONLY the corrected Python code. No explanation, no markdown fences. Just raw Python.
"""
    response = llm.invoke(prompt)
    content = (
        response.content if isinstance(response.content, str) else str(response.content)
    )
    fixed = content.replace("```python", "").replace("```", "").strip()

    print("[Fixer] Running sandbox to verify fix...")
    sandbox_result = _run_sandbox(fixed, test_script)
    print(f"[Fixer] Sandbox result:\n{sandbox_result}")

    print("--- FIXED CODE START ---")
    print(fixed)
    print("--- FIXED CODE END ---")
    print("--- SANDBOX RESULT START ---")
    print(sandbox_result)
    print("--- SANDBOX RESULT END ---")


if __name__ == "__main__":
    main()
