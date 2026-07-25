"""Tests for user / assistant / tool chat message storage."""

import json
import uuid

from app.models.agent import AgentStep
from app.services.chat_messages import (
    history_for_agent,
    message_for_assistant,
    message_for_tool,
    message_for_user,
    parse_assistant_step,
    parse_tool_output,
)


def test_message_for_assistant_stores_full_step():
    step = AgentStep(
        thinking="plan",
        code="print(1)",
        is_final_answer=False,
    )
    msg = message_for_assistant(step)
    assert msg.step_kind == "assistant"
    parsed = parse_assistant_step(msg.content)
    assert parsed.thinking == "plan"
    assert parsed.code == "print(1)"


def test_message_for_assistant_stores_final_step_and_artifact_ids_default_empty():
    step = AgentStep(
        thinking="done",
        final_answer="42",
        is_final_answer=True,
    )
    msg = message_for_assistant(step)
    assert parse_assistant_step(msg.content).is_final_answer is True
    assert msg.artifact_ids == []


def test_message_for_tool():
    msg = message_for_tool("Observation: True")
    assert msg.step_kind == "tool"
    assert parse_tool_output(msg.content) == "Observation: True"


def test_history_for_agent_keeps_only_users_and_final_answer_text():
    artifact_id = uuid.uuid4()
    final_message = message_for_assistant(
        AgentStep(
            thinking="private final trace with internal/minio/key",
            code="open('/private/workspace/output.png')",
            final_answer="The answer is 1.",
            is_final_answer=True,
        )
    ).model_copy(update={"artifact_ids": [artifact_id]})
    stored = [
        message_for_user('[{"type":"text","text":"hi"}]'),
        message_for_assistant(
            AgentStep(thinking="t", code="print(1)", is_final_answer=False)
        ),
        message_for_tool("Observation: 1"),
        final_message,
    ]
    agent_history = history_for_agent(stored)
    assert len(agent_history) == 2
    assert agent_history[0].step_kind == "user"
    assert agent_history[1].role == "assistant"
    assert agent_history[1].content == "The answer is 1."
    assert "private" not in agent_history[1].content
    assert "minio" not in agent_history[1].content
    assert "workspace" not in agent_history[1].content
    assert str(artifact_id) not in agent_history[1].content
    assert agent_history[1].artifact_ids == []


def test_message_for_user():
    msg = message_for_user(json.dumps([{"type": "text", "text": "hello"}]))
    assert msg.step_kind == "user"
    assert msg.role == "user"
