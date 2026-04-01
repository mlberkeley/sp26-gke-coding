import time
import uuid
from pathlib import Path

from kubernetes import client, config  # type: ignore[import-untyped]
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from .state import AgentState

test_path = Path(__file__).parent / "workspace" / "test_buggy_script.py"
buggy_file = Path(__file__).parent / "workspace" / "buggy_script.py"

llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)
resp = llm.invoke("print('hello world')")
print(resp)


def run_in_sandbox():
    # result = subprocess.run(["python3", str(test_path)], capture_output=True, text=True)
    # return result.stdout + "\n" + (result.stderr or "")
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    batch_v1 = client.BatchV1Api()
    core_v1 = client.CoreV1Api()
    job_name = f"sandbox-job-{uuid.uuid4().hex[:8]}"
    namespace = "default"
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    runtime_class_name="gvisor",
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            name="sandbox",
                            image="gcr.io/cogent-nimbus-489503-f6/sandbox:latest",
                            command=["python3", "/app/tests/test_buggy_script.py"],
                        )
                    ],
                )
            ),
            backoff_limit=0,
        ),
    )

    print(f"[sandbox] Creating job: {job_name}")
    batch_v1.create_namespaced_job(namespace=namespace, body=job)

    for _ in range(60):
        time.sleep(2)
        status = batch_v1.read_namespaced_job_status(job_name, namespace)
        if status.status.succeeded or status.status.failed:
            break

    pods = core_v1.list_namespaced_pod(
        namespace=namespace, label_selector=f"job-name={job_name}"
    )
    logs = ""
    for pod in pods.items:
        try:
            logs += core_v1.read_namespaced_pod_log(
                pod.metadata.name, namespace, timestamps=False
            )
        except Exception as e:
            logs += f"[log error] {e}\n"
    try:
        batch_v1.delete_namespaced_job(
            job_name,
            namespace,
            body=client.V1DeleteOptions(propagation_policy="Background"),
        )
    except Exception as e:
        print(f"[sandbox] Cleanup warning: {e}")

    print(f"[sandbox] Job {job_name} finished. Logs:\n{logs}")
    return logs


def run_tests_node(state: AgentState):
    print("run_tests_node")
    logs = run_in_sandbox()
    print("DEBUG: Sandbox logs:", logs)
    message = (
        AIMessage(content=f"Tests failed:\n{logs}")
        if "Traceback" in logs
        else AIMessage(content="PASSED: All tests passed.")
    )

    state["messages"] = state.get("messages", []) + [message]
    return {"messages": state["messages"]}


def suggest_fix_node(state: AgentState):
    print("suggest_fix_node")

    with open(buggy_file) as f:
        code = f.read()

    last_error = state["messages"][-1].content

    prompt = f"""
    The following Python code is failing tests.
    CODE:
    {code}

    ERROR:
    {last_error}

    Provide ONLY the corrected code. Do not explain. Just the code.
    """

    response = llm.invoke(prompt)
    return {"messages": [response]}


def apply_fix_node(state: AgentState):
    print("apply_fix_node")

    msg = state["messages"][-1]
    suggestion = msg.content

    if isinstance(suggestion, list):
        for block in suggestion:
            if isinstance(block, dict) and "text" in block:
                suggestion = block["text"]
                break

    print(f"DEBUG: Extracted suggestion: {repr(suggestion)}")

    if not suggestion:
        print("WARNING: Suggestion is empty!")
        return {
            "messages": [AIMessage(content="SYSTEM: Fix failed, empty suggestion.")]
        }

    clean_code = str(suggestion).replace("```python", "").replace("```", "").strip()

    with open("tests/buggy_script.py", "w") as f:
        f.write(clean_code)

    return {
        "messages": [AIMessage(content="SYSTEM: Applied LLM fix to file.")],
        "retry_count": state.get("retry_count", 0) + 1,
    }


def should_continue(state: AgentState):
    print("should_continue")

    last_msg = state["messages"][-1].content
    if "PASSED" in last_msg or state.get("retry_count", 0) >= 3:
        return END
    return "suggest_fix"
