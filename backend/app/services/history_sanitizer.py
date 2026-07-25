"""Build a bounded, data-URI-free copy of stored history for the LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.chat import Message

MAX_TOOL_OBSERVATION_CHARS = 20_000
MAX_HISTORY_MESSAGE_CHARS = 50_000
MAX_HISTORY_CHARS = 200_000
_TRUNCATED = "\n[truncated]"
_IMAGE_DATA_URI = re.compile(r"data:image/[^\s\"']*", re.IGNORECASE)


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    keep = max(0, limit - len(_TRUNCATED))
    return value[:keep] + _TRUNCATED


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _IMAGE_DATA_URI.sub("[image data removed]", value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def sanitize_content(content: str, *, limit: int = MAX_HISTORY_MESSAGE_CHARS) -> str:
    """Recursively sanitize JSON content and fall back safely for legacy text."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        sanitized = _sanitize_value(content)
    else:
        sanitized = json.dumps(
            _sanitize_value(parsed), ensure_ascii=False, separators=(",", ":")
        )
    return _bounded(str(sanitized), limit)


def sanitize_history(messages: list[Message]) -> list[Message]:
    """Return the newest bounded messages without changing the stored UI history."""
    sanitized: list[Message] = []
    for message in messages:
        limit = (
            MAX_TOOL_OBSERVATION_CHARS
            if message.step_kind == "tool"
            else MAX_HISTORY_MESSAGE_CHARS
        )
        sanitized.append(
            message.model_copy(update={"content": sanitize_content(message.content, limit=limit)})
        )

    selected_reversed: list[Message] = []
    total = 0
    for message in reversed(sanitized):
        remaining = MAX_HISTORY_CHARS - total
        if remaining <= 0:
            break
        if len(message.content) > remaining:
            message = message.model_copy(
                update={"content": _bounded(message.content, remaining)}
            )
        selected_reversed.append(message)
        total += len(message.content)
    return list(reversed(selected_reversed))
