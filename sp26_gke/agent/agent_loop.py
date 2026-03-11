from langchain_core.messages import HumanMessage

from .graph import build_graph


def run_agent():
    print("calling build_graph")
    app = build_graph()

    inputs = {"messages": [HumanMessage(content="Start fix loop")], "retry_count": 0}

    for output in app.stream(inputs):
        for node, state in output.items():
            print(f"\n[Node: {node}]")

            print(state["messages"][-1].content)
