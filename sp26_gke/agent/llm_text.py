"""Extract plain text from a langchain ChatModel response.

Recent Gemini SDK versions return ``response.content`` as a list of typed
content blocks (text, thinking, function-call, etc.) rather than a flat
string.  Calling ``str(response.content)`` on that list yields a Python repr
containing escaped JSON — useless for downstream parsing.

This helper concatenates the user-visible ``text`` blocks regardless of which
format the SDK returns.
"""

from __future__ import annotations

from typing import Any


def extract_text(response: Any) -> str:
    """Return the user-visible text content of an LLM response."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                block_type = block.get("type")
                text_field = block.get("text")
                if isinstance(text_field, str) and (
                    block_type is None or block_type == "text"
                ):
                    parts.append(text_field)
                continue
            text_attr = getattr(block, "text", None)
            if isinstance(text_attr, str):
                parts.append(text_attr)
        return "\n".join(parts)
    return str(content)
