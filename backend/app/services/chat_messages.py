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
        step_kind="user",
    )


def message_for_assistant(
    step: AgentStep, *, step_index: int | None = None, timestamp: datetime | None = None
) -> Message:
    now = timestamp or datetime.now(timezone.utc)
    return Message(
        role="assistant",
        content=step.model_dump_json(),
        timestamp=now,
        step_kind="assistant",
        step_index=step_index,
    )


def message_for_tool(
    output: str, *, step_index: int | None = None, timestamp: datetime | None = None
) -> Message:
    now = timestamp or datetime.now(timezone.utc)
    return Message(
        role="assistant",
        content=json.dumps({"output": output}),
        timestamp=now,
        step_kind="tool",
        step_index=step_index,
    )


def parse_assistant_step(content: str) -> AgentStep:
    return AgentStep.model_validate_json(content)


def parse_tool_output(content: str) -> str:
    data = json.loads(content)
    if isinstance(data, dict) and "output" in data:
        return str(data["output"])
    return content


def history_for_agent(messages: list[Message]) -> list[Message]:
    """Project stored trace history to prior user text and final answers only.

    The complete structured trace remains available to the UI in Redis, but code,
    thinking, observations, artifact identifiers, and executor paths never re-enter
    a later LLM request.
    """
    result: list[Message] = []
    for msg in messages:
        if msg.step_kind == "user":
            result.append(msg.model_copy(update={"artifact_ids": []}))
        elif msg.step_kind == "assistant":
            try:
                step = parse_assistant_step(msg.content)
            except Exception:
                continue
            if not step.is_final_answer:
                continue
            answer = step.final_answer or step.thinking
            if answer:
                result.append(
                    Message(
                        role="assistant",
                        content=answer,
                        timestamp=msg.timestamp,
                    )
                )
    return result
