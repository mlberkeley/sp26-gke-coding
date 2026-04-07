"""Diagnoser sub-agent: reads buggy code and classifies the bug type.

Optionally reads failure_context.txt from a previous attempt so it can
avoid repeating an approach that already failed.
"""

from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI


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

    prompt = f"""Analyze this Python code and identify the bug.

CODE:
{code}
{prior_section}
Provide a concise diagnosis: what is wrong, what type of bug it is (logic error, off-by-one, wrong operator, etc), and what the fix should be at a high level. Keep it under 3 sentences.
"""
    response = llm.invoke(prompt)
    content = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    print("--- AGENT OUTPUT START ---")
    print(content)
    print("--- AGENT OUTPUT END ---")


if __name__ == "__main__":
    main()
