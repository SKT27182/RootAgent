"""Chat message helpers: user / assistant (AgentStep) / tool."""

import json
from datetime import datetime, timezone

from app.models.agent import AgentStep
from app.models.chat import Message


def message_for_user(content: str, *, timestamp: datetime | None = None) -> Message:
    now = timestamp or datetime.now(timezone.utc)
    return Message(
        role="user",
        content=content,
        timestamp=now,
        is_reasoning=False,
        step_kind="user",
    )


def message_for_assistant(step: AgentStep, *, timestamp: datetime | None = None) -> Message:
    now = timestamp or datetime.now(timezone.utc)
    return Message(
        role="assistant",
        content=step.model_dump_json(),
        timestamp=now,
        is_reasoning=not step.is_final_answer,
        step_kind="assistant",
    )


def message_for_tool(output: str, *, timestamp: datetime | None = None) -> Message:
    now = timestamp or datetime.now(timezone.utc)
    return Message(
        role="assistant",
        content=json.dumps({"output": output}),
        timestamp=now,
        is_reasoning=True,
        step_kind="tool",
    )


def parse_assistant_step(content: str) -> AgentStep:
    return AgentStep.model_validate_json(content)


def parse_tool_output(content: str) -> str:
    data = json.loads(content)
    if isinstance(data, dict) and "output" in data:
        return str(data["output"])
    return content


def history_for_agent(messages: list[Message]) -> list[Message]:
    """Map stored user/assistant/tool rows to LLM conversation format."""
    result: list[Message] = []
    for msg in messages:
        if msg.step_kind == "user":
            result.append(msg)
        elif msg.step_kind == "assistant":
            result.append(
                Message(
                    role="assistant",
                    content=msg.content,
                    timestamp=msg.timestamp,
                    is_reasoning=msg.is_reasoning,
                )
            )
        elif msg.step_kind == "tool":
            result.append(
                Message(
                    role="user",
                    content=parse_tool_output(msg.content),
                    timestamp=msg.timestamp,
                    is_reasoning=True,
                )
            )
    return result
