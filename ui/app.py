"""Streamlit demo UI for the GKE Coding Agent."""

from __future__ import annotations

import difflib
import html as html_mod
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.k8s_client import cleanup, stream_logs, submit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent

EXAMPLES: dict[str, str] = {
    "Binary Search": (_ROOT / "examples" / "buggy_binary_search.py").read_text(),
    "Calculator": (_ROOT / "examples" / "buggy_calculator.py").read_text(),
    "Fibonacci": (_ROOT / "examples" / "buggy_fibonacci.py").read_text(),
    "Palindrome": (_ROOT / "examples" / "buggy_palindrome.py").read_text(),
}

ATTACKS: dict[str, str] = {
    "Attack 1 — Orchestrator Skip": (
        _ROOT / "examples" / "attack1_orchestrator_skip.py"
    ).read_text(),
    "Attack 2 — Diagnoser Poison": (
        _ROOT / "examples" / "attack2_diagnoser_poison.py"
    ).read_text(),
}

STEPS = [
    ("diagnose", "🔍", "Diagnose"),
    ("fix", "🔧", "Fix"),
    ("review", "✅", "Review"),
    ("result", "🏁", "Result"),
]

# ---------------------------------------------------------------------------
# Page config  (must be the first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="GKE Coding Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem !important; max-width: 100% !important; }

/* ── Pipeline ──────────────────────────────────────────────────────── */
.pipeline {
    display: flex; align-items: center; justify-content: center;
    gap: 6px; padding: 20px 16px;
    background: #161b22; border: 1px solid #21262d; border-radius: 10px;
}
.ps  { display:flex; flex-direction:column; align-items:center; gap:6px; min-width:80px; }
.pc  {
    width:56px; height:56px; border-radius:50%;
    display:flex; align-items:center; justify-content:center; font-size:24px;
    transition: all .35s ease;
}
.pl  { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.8px; }
.pa  { color:#30363d; font-size:22px; flex-shrink:0; }

.pending .pc  { background:#1c2128; border:2px solid #30363d; filter:opacity(.35); }
.pending .pl  { color:#484f58; }
.running .pc  { background:#1c2d4a; border:2px solid #4285F4;
                box-shadow:0 0 16px rgba(66,133,244,.5);
                animation:glow 1.6s ease-in-out infinite; }
.running .pl  { color:#4285F4; }
.done    .pc  { background:#162a22; border:2px solid #34A853; }
.done    .pl  { color:#34A853; }
.failed  .pc  { background:#2d1616; border:2px solid #EA4335; }
.failed  .pl  { color:#EA4335; }
@keyframes glow {
    0%,100% { box-shadow:0 0 8px  rgba(66,133,244,.3); }
    50%      { box-shadow:0 0 24px rgba(66,133,244,.7); }
}

/* ── Log box ───────────────────────────────────────────────────────── */
.logbox {
    background:#010409; border:1px solid #21262d; border-radius:8px;
    padding:14px 16px;
    font-family:'SFMono-Regular','Cascadia Code',Consolas,monospace;
    font-size:12px; line-height:1.65;
    height:380px; overflow-y:auto;
    white-space:pre-wrap; word-break:break-word;
}

/* ── Code box (fixed code) ─────────────────────────────────────────── */
.codebox {
    background:#010409; border:1px solid #21262d; border-radius:8px;
    padding:14px 16px;
    font-family:'SFMono-Regular','Cascadia Code',Consolas,monospace;
    font-size:12.5px; line-height:1.7; color:#c9d1d9;
    max-height:280px; overflow-y:auto; white-space:pre;
}

/* ── Diff box ──────────────────────────────────────────────────────── */
.diffbox {
    background:#010409; border:1px solid #21262d; border-radius:8px;
    padding:14px 16px;
    font-family:'SFMono-Regular','Cascadia Code',Consolas,monospace;
    font-size:12px; line-height:1.65;
    max-height:260px; overflow-y:auto; white-space:pre;
}
.da { color:#3fb950; background:rgba(56,139,53,.18); display:block; }
.dd { color:#f85149; background:rgba(248,81,73,.18); display:block; }
.dh { color:#8b949e; display:block; }
.dc { color:#c9d1d9; display:block; }

/* ── Result banner ─────────────────────────────────────────────────── */
.banner {
    display:flex; align-items:center; gap:14px;
    padding:15px 20px; border-radius:8px; margin-bottom:14px;
}
.banner-p { background:#162a22; border:1px solid #34A853; }
.banner-f { background:#2d1616; border:1px solid #EA4335; }
.bi { font-size:28px; }
.bt { font-weight:700; font-size:15px; color:#f0f6fc; }
.bs { font-size:11px; color:#8b949e; margin-top:2px; }

/* ── Section labels ────────────────────────────────────────────────── */
.slabel {
    font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:1px; color:#8b949e; margin:14px 0 6px 2px;
}

/* ── Header ────────────────────────────────────────────────────────── */
.hdr {
    display:flex; justify-content:space-between; align-items:center;
    padding-bottom:18px; border-bottom:1px solid #21262d; margin-bottom:22px;
}
.htitle { font-size:26px; font-weight:700; color:#f0f6fc; letter-spacing:-.5px; }
.htitle em { font-style:normal; color:#4285F4; }
.hbadges { display:flex; gap:8px; align-items:center; }
.hb { padding:4px 12px; border-radius:16px; font-size:11px; font-weight:600; }
.hbg { background:#1c2d4a; color:#4285F4; }
.hbm { background:#162a22; color:#34A853; }
.hbv { background:#21262d; color:#8b949e; font-family:monospace; }

/* ── Input code textarea ───────────────────────────────────────────── */
.stTextArea textarea {
    background:#010409 !important; color:#c9d1d9 !important;
    font-family:'SFMono-Regular',Consolas,monospace !important;
    font-size:12.5px !important; border:1px solid #21262d !important;
    border-radius:8px !important; line-height:1.7 !important;
}
.stTextArea label {
    font-size:10px !important; font-weight:700 !important;
    text-transform:uppercase !important; letter-spacing:1px !important;
    color:#8b949e !important;
}

/* ── Example chips ─────────────────────────────────────────────────── */
div[data-testid="stHorizontalBlock"] .stButton button {
    background:#1c2128 !important; border:1px solid #30363d !important;
    color:#8b949e !important; font-size:11px !important;
    padding:5px 4px !important; border-radius:20px !important; width:100% !important;
    transition: all .2s;
}
div[data-testid="stHorizontalBlock"] .stButton button:hover {
    border-color:#4285F4 !important; color:#e6edf3 !important; background:#21262d !important;
}
/* Attack buttons */
button[key^="atk_"], div[data-testid="stHorizontalBlock"]:has(button[key^="atk_"]) .stButton button {
    border-color:#EA4335 !important; color:#EA4335 !important;
}
div[data-testid="stHorizontalBlock"]:has(button[key^="atk_"]) .stButton button:hover {
    background:#2d1616 !important; border-color:#FF6B6B !important; color:#FF6B6B !important;
}

/* ── Run button ────────────────────────────────────────────────────── */
div[data-testid="stButton"]:has(button[kind="primary"]) button {
    background:linear-gradient(135deg,#4285F4,#1a73e8) !important;
    border:none !important; color:#fff !important;
    font-weight:700 !important; font-size:14px !important;
    padding:12px 0 !important; border-radius:8px !important; width:100% !important;
    letter-spacing:.3px !important; box-shadow:0 4px 14px rgba(66,133,244,.35) !important;
    transition: all .2s !important;
}
div[data-testid="stButton"]:has(button[kind="primary"]) button:hover {
    box-shadow:0 6px 20px rgba(66,133,244,.5) !important;
    transform:translateY(-1px) !important;
}
div[data-testid="stButton"]:has(button[kind="primary"]) button:disabled {
    background:#21262d !important; color:#484f58 !important;
    box-shadow:none !important; transform:none !important;
}

/* ── Divider ───────────────────────────────────────────────────────── */
hr { border-color:#21262d !important; margin:12px 0 !important; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pipeline_html(states: dict[str, str]) -> str:
    parts = []
    for i, (key, icon, label) in enumerate(STEPS):
        s = states.get(key, "pending")
        parts.append(
            f'<div class="ps {s}">'
            f'<div class="pc">{icon}</div>'
            f'<div class="pl">{label}</div>'
            f"</div>"
        )
        if i < len(STEPS) - 1:
            parts.append('<div class="pa">›</div>')
    return '<div class="pipeline">' + "".join(parts) + "</div>"


def _colorize(line: str) -> str:
    e = html_mod.escape(line)
    if not line.strip():
        return '<span style="color:#21262d">&nbsp;</span>'
    if "AGENT STATUS: PASSED" in line:
        return f'<span style="color:#3fb950;font-weight:600">{e}</span>'
    if "AGENT STATUS: FAILED" in line:
        return f'<span style="color:#f85149;font-weight:600">{e}</span>'
    if line.startswith("---"):
        return f'<span style="color:#484f58">{e}</span>'
    if line.startswith("[Orchestrator]"):
        return f'<span style="color:#FFA94D">{e}</span>'
    if line.startswith("[K8s]"):
        return f'<span style="color:#74C0FC">{e}</span>'
    if line.startswith("[PolicyGuard]"):
        color = "#FF6B6B" if "DENY" in line or "BLOCKED" in line else "#74C0FC"
        return f'<span style="color:{color};font-weight:600">{e}</span>'
    if line.startswith("[Diagnoser"):
        return f'<span style="color:#DA77F2">{e}</span>'
    if line.startswith("[Fixer"):
        return f'<span style="color:#63E6BE">{e}</span>'
    if line.startswith("[Reviewer"):
        return f'<span style="color:#A9E34B">{e}</span>'
    return f'<span style="color:#8b949e">{e}</span>'


def _diff_html(original: str, fixed: str) -> str:
    lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="original.py",
            tofile="fixed.py",
            lineterm="",
        )
    )
    if not lines:
        return (
            '<div class="diffbox">'
            '<span style="color:#8b949e">No changes detected.</span>'
            "</div>"
        )
    body = ""
    for ln in lines:
        e = html_mod.escape(ln)
        if ln.startswith("+") and not ln.startswith("+++"):
            body += f'<span class="da">{e}</span>'
        elif ln.startswith("-") and not ln.startswith("---"):
            body += f'<span class="dd">{e}</span>'
        elif ln.startswith("@@"):
            body += f'<span class="dh">{e}</span>'
        else:
            body += f'<span class="dc">{e}</span>'
    return f'<div class="diffbox">{body}</div>'


def _update_states(line: str, states: dict[str, str]) -> dict[str, str]:
    s = dict(states)

    if "[Orchestrator] Step" in line and " — " in line:
        try:
            action = line.split(": ", 2)[2].split(" — ")[0].strip().upper()
        except IndexError:
            action = ""

        if action == "DIAGNOSE":
            if s.get("diagnose") == "done":
                # Re-diagnosis: reset downstream steps
                s["fix"] = "pending"
                s["review"] = "pending"
                s["result"] = "pending"
            s["diagnose"] = "running"
        elif action == "FIX":
            s["diagnose"] = "done"
            s["fix"] = "running"
        elif action == "REVIEW":
            s["fix"] = "done"
            s["review"] = "running"
        elif action in ("ACCEPT", "GIVE_UP"):
            for k in ("diagnose", "fix", "review"):
                if s.get(k) == "running":
                    s[k] = "done"
            s["result"] = "running"

    if "[Orchestrator] Diagnosis:" in line:
        s["diagnose"] = "done"
    if "[Orchestrator] Fixer sandbox:" in line:
        s["fix"] = "done"
    if "[Orchestrator] Reviewer sandbox:" in line:
        s["review"] = "done"
    if "AGENT STATUS: PASSED" in line:
        for k in ("diagnose", "fix", "review"):
            if s.get(k) == "running":
                s[k] = "done"
        s["result"] = "done"
    if "AGENT STATUS: FAILED" in line:
        for k in ("diagnose", "fix", "review"):
            if s.get(k) == "running":
                s[k] = "done"
        s["result"] = "failed"

    return s


def _stream_agent(
    code: str,
    pipeline_ph: st.delta_generator.DeltaGenerator,
    info_ph: st.delta_generator.DeltaGenerator,
    log_ph: st.delta_generator.DeltaGenerator,
    result_ph: st.delta_generator.DeltaGenerator,
) -> None:
    states: dict[str, str] = {k: "pending" for k, _, _ in STEPS}
    pipeline_ph.markdown(_pipeline_html(states), unsafe_allow_html=True)
    info_ph.markdown(
        '<div class="slabel">Submitting job to GKE…</div>', unsafe_allow_html=True
    )
    log_ph.markdown(
        '<div class="logbox"><span style="color:#484f58">Waiting for pod to schedule…</span></div>',
        unsafe_allow_html=True,
    )

    try:
        job_name, cm_name = submit(code)
    except Exception as exc:
        result_ph.error(f"Failed to submit job: {exc}")
        return

    info_ph.markdown(
        f'<div class="slabel">Job: <code style="color:#74C0FC">{job_name}</code></div>',
        unsafe_allow_html=True,
    )

    log_lines: list[str] = []
    final_code_lines: list[str] = []
    capturing_final = False
    agent_status: str | None = None

    try:
        for line in stream_logs(job_name):
            if "--- FINAL CODE START ---" in line:
                capturing_final = True
                log_lines.append(line)
                continue
            if "--- FINAL CODE END ---" in line:
                capturing_final = False
                log_lines.append(line)
                continue
            if capturing_final:
                final_code_lines.append(line)
                continue

            if "AGENT STATUS: PASSED" in line:
                agent_status = "passed"
            elif "AGENT STATUS: FAILED" in line:
                agent_status = "failed"

            states = _update_states(line, states)
            log_lines.append(line)

            pipeline_ph.markdown(_pipeline_html(states), unsafe_allow_html=True)

            tail = log_lines[-80:]
            colored = "<br>".join(_colorize(ln) for ln in tail)
            log_ph.markdown(
                f'<div class="logbox">{colored}</div>', unsafe_allow_html=True
            )
    finally:
        cleanup(job_name, cm_name)

    # Final pipeline state
    pipeline_ph.markdown(_pipeline_html(states), unsafe_allow_html=True)

    fixed_code = "\n".join(final_code_lines) if final_code_lines else code

    if agent_status == "passed":
        banner_cls = "banner-p"
        icon = "✅"
        title = "Agent Fixed the Code Successfully"
        subtitle = "All tests passed &nbsp;·&nbsp; gVisor sandbox verified"
    else:
        banner_cls = "banner-f"
        icon = "⚠️"
        title = "Agent Could Not Fix the Code"
        subtitle = "Max retry limit reached &nbsp;·&nbsp; showing best attempt"

    diff = _diff_html(code, fixed_code)
    code_block = f'<div class="codebox">{html_mod.escape(fixed_code)}</div>'

    result_ph.markdown(
        f"""
<div class="banner {banner_cls}">
  <div class="bi">{icon}</div>
  <div><div class="bt">{title}</div><div class="bs">{subtitle}</div></div>
</div>
<div class="slabel">Fixed Code</div>
{code_block}
<div class="slabel">Changes (Diff)</div>
{diff}
""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "code" not in st.session_state:
    st.session_state.code = EXAMPLES["Fibonacci"]
if "running" not in st.session_state:
    st.session_state.running = False

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    """
<div class="hdr">
  <div class="htitle">GKE <em>Coding Agent</em></div>
  <div class="hbadges">
    <span class="hb hbg">Google Cloud</span>
    <span class="hb hbm">ML@Berkeley</span>
    <span class="hb hbv">Spring 2026</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown('<div class="slabel">Input Code</div>', unsafe_allow_html=True)

    code_value = st.text_area(
        "input_code",
        value=st.session_state.code,
        height=310,
        label_visibility="collapsed",
    )
    st.session_state.code = code_value

    st.markdown('<div class="slabel">Load Example</div>', unsafe_allow_html=True)

    ex_cols = st.columns(len(EXAMPLES))
    for col, name in zip(ex_cols, EXAMPLES):
        if col.button(name, key=f"ex_{name}", use_container_width=True):
            st.session_state.code = EXAMPLES[name]
            st.rerun()

    st.markdown(
        '<div class="slabel" style="color:#FF6B6B;margin-top:10px">⚠ Prompt Injection Attacks</div>',
        unsafe_allow_html=True,
    )
    atk_cols = st.columns(len(ATTACKS))
    for col, name in zip(atk_cols, ATTACKS):
        if col.button(name, key=f"atk_{name}", use_container_width=True):
            st.session_state.code = ATTACKS[name]
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    run_clicked = st.button(
        "▶  Run Agent",
        type="primary",
        disabled=st.session_state.running,
        use_container_width=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        """
<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 14px;">
  <div class="slabel" style="margin-top:0">Legend</div>
  <div style="font-size:11px;line-height:2;font-family:monospace">
    <span style="color:#FFA94D">■</span> Orchestrator &nbsp;
    <span style="color:#74C0FC">■</span> Kubernetes &nbsp;
    <span style="color:#DA77F2">■</span> Diagnoser<br>
    <span style="color:#63E6BE">■</span> Fixer &nbsp;
    <span style="color:#A9E34B">■</span> Reviewer &nbsp;
    <span style="color:#FF6B6B">■</span> PolicyGuard DENY<br>
    <span style="color:#3fb950">■</span> Passed &nbsp;
    <span style="color:#f85149">■</span> Failed
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

with right:
    st.markdown('<div class="slabel">Pipeline Status</div>', unsafe_allow_html=True)
    pipeline_ph = st.empty()
    info_ph = st.empty()
    pipeline_ph.markdown(
        _pipeline_html({k: "pending" for k, _, _ in STEPS}), unsafe_allow_html=True
    )
    st.markdown('<div class="slabel">Live Logs</div>', unsafe_allow_html=True)
    log_ph = st.empty()
    log_ph.markdown(
        '<div class="logbox"><span style="color:#484f58">Logs will appear here once the agent starts…</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="slabel">Result</div>', unsafe_allow_html=True)
    result_ph = st.empty()
    result_ph.markdown(
        '<div style="color:#484f58;font-size:12px;padding:8px 2px">Result will appear after the agent finishes.</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if run_clicked:
    st.session_state.running = True
    _stream_agent(
        st.session_state.code,
        pipeline_ph,
        info_ph,
        log_ph,
        result_ph,
    )
    st.session_state.running = False
