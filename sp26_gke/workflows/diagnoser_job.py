"""Diagnoser sub-agent: reads buggy code and classifies the bug type.

Optionally reads failure_context.txt from a previous attempt so it can
avoid repeating an approach that already failed.
"""
import json
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI

from sp26_gke.agent.llm_text import extract_text


def main() -> None:
    code = Path("/input/buggy_script.py").read_text()
    failure_context_path = Path("/input/failure_context.txt")
    failure_context = (
        failure_context_path.read_text() if failure_context_path.exists() else None
    )

    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    prior_section = (
        f"\nPREVIOUS ATTEMPT CONTEXT (use this to try a different approach):\n{failure_context}\n"
        if failure_context
        else ""
    )

    prompt = f"""You are a reasoning agent for buggy Python code. Analyze the code and return ONLY valid JSON with this exact schema:

    {{
        "hypothesis": "short bug hypothesis",
        "evidence": ["evidence item 1", "evidence item 2", "evidence item 3"],
        "reasoning": "brief visible rationale, 1-3 sentences",
        "confidence": 0.0,
        "bug_type": "logic error | off-by-one | wrong operator | missing case | state bug | unknown",
        "recommended_fix": "high-level fix only, no code"
    }}

Rules:
- confidence must be a float between 0 and 1
- evidence must be concrete and grounded in the code
- do not include markdown
- do not include any text outside the JSON

CODE:
{code}
{prior_section}
Provide a concise diagnosis: what is wrong, what type of bug it is (logic error, off-by-one, wrong operator, etc), and what the fix should be at a high level. Keep it under 3 sentences.
"""
    response = llm.invoke(prompt)
    content = extract_text(response)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {
            "hypothesis": "Unable to parse structured diagnosis",
            "evidence": [content],
            "reasoning": "Model did not return valid JSON.",
            "confidence": 0.0,
            "bug_type": "unknown",
            "recommended_fix": "Retry diagnosis with stricter formatting."
        }

    trace = {
        "agent": "diagnoser",
        "output": parsed,
    }

    print("--- AGENT OUTPUT START ---")
    print(json.dumps(trace, indent=2))
    print("--- AGENT OUTPUT END ---")


if __name__ == "__main__":
    main()
