"""Tests for user / assistant / tool chat message storage."""

import json

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
    assert msg.is_reasoning is True
    parsed = parse_assistant_step(msg.content)
    assert parsed.thinking == "plan"
    assert parsed.code == "print(1)"


def test_message_for_assistant_final_not_reasoning():
    step = AgentStep(
        thinking="done",
        final_answer="42",
        is_final_answer=True,
    )
    msg = message_for_assistant(step)
    assert msg.is_reasoning is False
    assert parse_assistant_step(msg.content).is_final_answer is True


def test_message_for_tool():
    msg = message_for_tool("Observation: True")
    assert msg.step_kind == "tool"
    assert parse_tool_output(msg.content) == "Observation: True"


def test_history_for_agent_maps_tool_to_user():
    stored = [
        message_for_user('[{"type":"text","text":"hi"}]'),
        message_for_assistant(
            AgentStep(thinking="t", code="print(1)", is_final_answer=False)
        ),
        message_for_tool("Observation: 1"),
    ]
    agent_history = history_for_agent(stored)
    assert agent_history[0].step_kind == "user"
    assert agent_history[1].role == "assistant"
    assert "thinking" in agent_history[1].content
    assert agent_history[2].role == "user"
    assert agent_history[2].content == "Observation: 1"


def test_message_for_user():
    msg = message_for_user(json.dumps([{"type": "text", "text": "hello"}]))
    assert msg.step_kind == "user"
    assert msg.role == "user"
