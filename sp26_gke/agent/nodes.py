from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from sp26_gke.agent.state import AgentState
from sp26_gke.sandbox.sandbox_runner import run_in_sandbox

test_path = Path("/workspace/test_buggy_script.py")
buggy_file = Path("/workspace/buggy_script.py")

llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)


def run_tests_node(state: AgentState):
    logs = run_in_sandbox()
    message = (
        AIMessage(content=f"Tests failed:\n{logs}")
        if "Traceback" in logs
        else AIMessage(content="PASSED: All tests passed.")
    )

    state["messages"] = state.get("messages", []) + [message]
    return {"messages": state["messages"]}


def suggest_fix_node(state: AgentState):
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
    msg = state["messages"][-1]
    suggestion = msg.content

    if isinstance(suggestion, list):
        for block in suggestion:
            if isinstance(block, dict) and "text" in block:
                suggestion = block["text"]
                break

    if not suggestion:
        return {
            "messages": [AIMessage(content="SYSTEM: Fix failed, empty suggestion.")]
        }

    clean_code = str(suggestion).replace("```python", "").replace("```", "").strip()

    with open(buggy_file, "w") as f:
        f.write(clean_code)

    return {
        "messages": [AIMessage(content="SYSTEM: Applied LLM fix to file.")],
        "retry_count": state.get("retry_count", 0) + 1,
    }


def should_continue(state: AgentState):
    last_msg = state["messages"][-1].content
    if "PASSED" in last_msg or state.get("retry_count", 0) >= 3:
        return END
    return "suggest_fix"
