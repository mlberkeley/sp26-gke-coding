"""Diagnoser sub-agent: reads buggy code and classifies the bug type."""

from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI


def main() -> None:
    code = Path("/input/buggy_script.py").read_text()
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

    prompt = f"""Analyze this Python code and identify the bug.

CODE:
{code}

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
