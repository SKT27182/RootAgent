from typing import Any


def format_user_message(query: str) -> list[dict[str, Any]]:
    """Build the text-only persisted user message.

    Artifact bytes are staged into a private run workspace and only bounded metadata
    is added transiently to the LLM copy by ``ChatRunService``.
    """

    return [{"type": "text", "text": query}]
