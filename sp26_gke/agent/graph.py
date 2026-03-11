from langgraph.graph import START, StateGraph

from .nodes import apply_fix_node, run_tests_node, should_continue, suggest_fix_node
from .state import AgentState


def build_graph():
    print("building graph")
    workflow = StateGraph(AgentState)

    workflow.add_node("run_tests", run_tests_node)
    workflow.add_node("suggest_fix", suggest_fix_node)
    workflow.add_node("apply_fix", apply_fix_node)

    print("adding nodes")

    workflow.add_edge(START, "run_tests")

    workflow.add_conditional_edges("run_tests", should_continue)

    workflow.add_edge("suggest_fix", "apply_fix")
    workflow.add_edge("apply_fix", "run_tests")

    return workflow.compile()
