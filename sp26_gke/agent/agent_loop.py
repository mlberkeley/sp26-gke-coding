from pathlib import Path

from langchain_core.messages import HumanMessage

from .graph import build_graph

BUGGY_FILE = Path("/workspace/buggy_script.py")


def run_agent():
    print("calling build_graph")
    app = build_graph()

    inputs = {"messages": [HumanMessage(content="Start fix loop")], "retry_count": 0}

    last_content = ""
    for output in app.stream(inputs):
        for node, state in output.items():
            print(f"\n[Node: {node}]")
            last_content = state["messages"][-1].content
            print(last_content)

    passed = "PASSED" in last_content
    print(f"\n--- AGENT STATUS: {'PASSED' if passed else 'FAILED'} ---")
    print("--- FINAL CODE START ---")
    print(BUGGY_FILE.read_text())
    print("--- FINAL CODE END ---")
