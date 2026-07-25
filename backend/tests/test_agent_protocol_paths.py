from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.agent import Agent, FunctionTool
from app.agent.executor import FinalAnswerException
from app.models.agent import AgentStep
from app.models.chat import Message


def documented_tool(value: int, factor: int = 2) -> int:
    """Multiply a value by the requested factor."""
    return value * factor


def test_agent_builds_prompt_with_tools_history_and_transient_artifacts() -> None:
    agent = Agent(additional_functions={"documented_tool": documented_tool})
    prompt = agent.tools["documented_tool"].to_code_prompt()
    assert prompt.startswith("def documented_tool(")
    assert "factor: 'int' = 2" in prompt
    assert "Multiply a value" in prompt

    messages = agent._initialize_messages(
        "analyze this",
        [
            Message(role="user", content='[{"type":"text","text":"prior"}]'),
            Message(role="assistant", content="[malformed type text"),
        ],
        "<artifacts>safe.csv</artifacts>",
    )
    assert "Uploaded files available in this chat" not in messages[0]["content"]
    assert messages[1]["content"][0]["text"] == "prior"
    assert messages[2]["content"] == "[malformed type text"
    assert messages[-1]["content"] == [
        {"type": "text", "text": "analyze this"},
        {"type": "text", "text": "<artifacts>safe.csv</artifacts>"},
    ]

    with_uploads = agent._initialize_messages(
        "analyze this",
        uploaded_artifacts=[
            {
                "filename": "sales.csv",
                "ref": "artifact_abc",
                "content_type": "text/csv",
                "size": 12,
            }
        ],
    )
    system = with_uploads[0]["content"]
    assert "Uploaded files available in this chat" in system
    assert "sales.csv" in system
    assert "read_artifact using the filename" in system
    assert "filenames are unique per chat" in system


@pytest.mark.asyncio
async def test_agent_generate_step_accepts_dict_and_formats_history() -> None:
    agent = Agent()
    agent.llm.agenerate = AsyncMock(
        return_value={
            "thinking": "done",
            "final_answer": "result",
            "is_final_answer": True,
        }
    )
    step = await agent._generate_step([])
    assert isinstance(step, AgentStep)
    assert step.final_answer == "result"
    assert '"is_final_answer":true' in agent._format_step_for_history(step)


@pytest.mark.asyncio
async def test_agent_run_handles_executor_final_answer_errors_and_max_steps() -> None:
    executor = AsyncMock()
    executor.execute.return_value = FinalAnswerException("tool result")
    agent = Agent(executor=executor)
    agent._generate_step = AsyncMock(
        return_value=AgentStep(thinking="compute", code="final_answer(7)")
    )
    answer, history = await agent.run(query="compute")
    assert answer == "tool result"
    assert len(history) == 1

    agent = Agent(executor=AsyncMock())
    agent.max_steps = 2
    agent._generate_step = AsyncMock(
        side_effect=[
            AgentStep(thinking="need code"),
            RuntimeError("provider unavailable"),
        ]
    )
    answer, history = await agent.run(query="compute")
    assert answer == "Agent reached maximum steps without a final answer."
    assert any("Provide code" in item["content"] for item in history)
    assert any("provider unavailable" in item["content"] for item in history)


@pytest.mark.asyncio
async def test_agent_stream_emits_code_observation_then_final_step() -> None:
    executor = AsyncMock()
    executor.execute.return_value = "42"
    agent = Agent(executor=executor)
    agent._generate_step = AsyncMock(
        side_effect=[
            AgentStep(thinking="compute", code="print(6 * 7)"),
            AgentStep(
                thinking="done", final_answer="42", is_final_answer=True
            ),
        ]
    )

    events = [event async for event in agent.run_stream(query="compute")]
    assert [event["type"] for event in events] == ["step", "tool", "step"]
    assert [event["step_index"] for event in events] == [0, 0, 1]
    assert events[1]["content"] == "Observation: 42"
    assert events[-1]["step"]["final_answer"] == "42"


@pytest.mark.asyncio
async def test_agent_stream_handles_tool_final_error_and_max_steps() -> None:
    executor = AsyncMock()
    executor.execute.return_value = FinalAnswerException("finished in tool")
    agent = Agent(executor=executor)
    agent._generate_step = AsyncMock(
        return_value=AgentStep(thinking="compute", code="final_answer('done')")
    )
    events = [event async for event in agent.run_stream(query="compute")]
    assert [event["type"] for event in events] == ["step", "step"]
    assert events[0]["step"]["code"] == "final_answer('done')"
    assert events[1]["step"]["final_answer"] == "finished in tool"

    agent = Agent(executor=AsyncMock())
    agent.max_steps = 2
    agent._generate_step = AsyncMock(
        side_effect=[AgentStep(thinking="no code"), RuntimeError("bad response")]
    )
    events = [event async for event in agent.run_stream(query="compute")]
    assert [event["type"] for event in events] == ["step", "tool", "step"]
    assert "Provide code" in events[1]["content"]
    assert events[-1]["step"]["is_final_answer"] is True


def test_function_tool_without_docstring_uses_empty_prompt_body() -> None:
    with patch.object(documented_tool, "__doc__", None):
        tool = FunctionTool(documented_tool)
    assert '""""""' in tool.to_code_prompt()
