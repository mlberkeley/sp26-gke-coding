"""Run the sentinel classifier against an arbitrary input, locally.

Reuses the same _PROMPT and parser as the deployed sentinel_job, so the verdict
matches what would happen on GKE — minus the per-pod overhead.

Usage:
    GOOGLE_API_KEY=... pixi run python benchmarks/sentinel_test.py path/to/attack.py
    cat attack.py | GOOGLE_API_KEY=... pixi run python benchmarks/sentinel_test.py -
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_google_genai import ChatGoogleGenerativeAI

from sp26_gke.agent.llm_text import extract_text
from sp26_gke.workflows.sentinel_job import _PROMPT, _first_word, _strip_emphasis


def classify(code: str) -> dict:
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)
    response = llm.invoke(_PROMPT.format(code=code))
    content = extract_text(response)

    verdict = ""
    reason = ""
    for raw_line in content.splitlines():
        line = _strip_emphasis(raw_line)
        upper = line.upper()
        if upper.startswith("VERDICT:"):
            after = line.split(":", 1)[1] if ":" in line else ""
            verdict = _first_word(after).rstrip(".,;:!")
        elif upper.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip() if ":" in line else ""

    if verdict not in ("clean", "flagged"):
        verdict = "flagged"
        reason = reason or "classifier output did not match expected format"

    return {"raw": content, "verdict": verdict, "reason": reason}


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    code = sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text()

    result = classify(code)
    print("=== INPUT ===")
    print(code.rstrip())
    print()
    print("=== RAW LLM RESPONSE ===")
    print(result["raw"].rstrip())
    print()
    print(f"=== VERDICT: {result['verdict']} ===")
    print(f"reason: {result['reason']}")


if __name__ == "__main__":
    main()
