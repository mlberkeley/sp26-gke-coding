"""
Streamlit UI for the interactive coding agent.

Paste buggy Python code, submit it to GKE, and watch the agent fix it live.
"""

import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from ui.k8s_client import cleanup, stream_logs, submit

EXAMPLE_CODE = """\
def add(a, b):
    return a - b
"""

st.set_page_config(page_title="Coding Agent", page_icon="🤖", layout="wide")
st.title("🤖 Coding Agent")
st.caption(
    "Paste buggy Python code. The agent will fix it using an LLM + sandboxed testing on GKE."
)

state = st.session_state

# ── Idle: show input form ──────────────────────────────────────────────────────
if state.get("phase") not in ("running", "done"):
    code = st.text_area(
        "Paste your buggy Python code:",
        value=EXAMPLE_CODE,
        height=200,
        key="code_input",
    )
    if st.button("▶ Run Agent", type="primary"):
        with st.spinner("Submitting job to GKE..."):
            job_name, cm_name = submit(code)
        state["phase"] = "running"
        state["job_name"] = job_name
        state["cm_name"] = cm_name
        state["original_code"] = code
        st.rerun()

# ── Running: stream logs ───────────────────────────────────────────────────────
elif state.get("phase") == "running":
    st.info(f"⏳ Job `{state['job_name']}` running on GKE...")

    log_box = st.empty()
    all_lines: list[str] = []
    final_code_lines: list[str] = []
    capturing = False
    agent_status = None

    for line in stream_logs(state["job_name"]):
        if "--- AGENT STATUS: PASSED ---" in line:
            agent_status = "PASSED"
        elif "--- AGENT STATUS: FAILED ---" in line:
            agent_status = "FAILED"
        elif "--- FINAL CODE START ---" in line:
            capturing = True
        elif "--- FINAL CODE END ---" in line:
            capturing = False
        elif capturing:
            final_code_lines.append(line)
        else:
            all_lines.append(line)
            log_box.code("\n".join(all_lines[-60:]), language="")

    state["phase"] = "done"
    state["agent_status"] = agent_status
    state["final_code"] = "\n".join(final_code_lines)
    state["logs"] = "\n".join(all_lines)
    st.rerun()

# ── Done: show results ─────────────────────────────────────────────────────────
elif state.get("phase") == "done":
    if state.get("agent_status") == "PASSED":
        st.success("✅ Agent fixed the code!")
    else:
        st.warning("⚠️ Agent reached max retries — showing best attempt.")

    original = state.get("original_code", "")
    fixed = state.get("final_code", "")

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="original",
            tofile="fixed",
        )
    )

    st.subheader("Diff")
    st.code(diff or "(no changes)", language="diff")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Original")
        st.code(original, language="python")
    with col2:
        st.subheader("Fixed")
        st.code(fixed, language="python")

    with st.expander("Full logs"):
        st.code(state.get("logs", ""), language="")

    if st.button("🔄 Run Again"):
        cleanup(state["job_name"], state["cm_name"])
        for key in (
            "phase",
            "job_name",
            "cm_name",
            "original_code",
            "agent_status",
            "final_code",
            "logs",
        ):
            state.pop(key, None)
        st.rerun()
