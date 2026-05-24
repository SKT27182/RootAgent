import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.agent import Agent
from app.agent.executor import CodeExecutor, FinalAnswerException
from app.models.agent import AgentStep
from app.models.chat import Message
from app.services.redis_store import RedisStore


@pytest.fixture
def mock_redis_client():
    client = MagicMock()
    client.rpush = AsyncMock()
    client.lrange = AsyncMock(return_value=[])
    client.delete = AsyncMock(return_value=1)
    client.zadd = AsyncMock()
    client.zscore = AsyncMock(return_value=None)
    client.zrem = AsyncMock()
    client.expire = AsyncMock()
    client.type = AsyncMock(return_value="none")
    client.zrevrange = AsyncMock(return_value=[])
    return client


@pytest.fixture
def redis_store(mock_redis_client):
    with patch(
        "app.services.redis_store.redis.Redis", return_value=mock_redis_client
    ):
        yield RedisStore()


@pytest.mark.asyncio
async def test_agent_step_json_final_answer():
    step = AgentStep(
        thinking="done",
        code=None,
        final_answer="Hello user",
        is_final_answer=True,
    )
    assert step.is_final_answer
    assert step.final_answer == "Hello user"


@pytest.mark.asyncio
async def test_agent_run_final_answer_without_code():
    agent = Agent(additional_functions={})
    mock_step = AgentStep(
        thinking="answer",
        final_answer="42",
        is_final_answer=True,
    )

    with patch.object(agent, "_generate_step", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_step
        answer, steps = await agent.run(query="What is 6*7?", history=[])
        assert answer == "42"
        assert len(steps) >= 1


@pytest.mark.asyncio
async def test_agent_run_executes_code_then_final():
    agent = Agent(additional_functions={})
    steps_sequence = [
        AgentStep(
            thinking="compute",
            code="print(6*7)",
            is_final_answer=False,
        ),
        AgentStep(
            thinking="done",
            final_answer="42",
            is_final_answer=True,
        ),
    ]

    with patch.object(agent, "_generate_step", new_callable=AsyncMock) as mock_gen:
        mock_gen.side_effect = steps_sequence
        answer, _ = await agent.run(query="compute", history=[])
        assert answer == "42"


@pytest.mark.asyncio
async def test_redis_no_function_keys(redis_store, mock_redis_client):
    await redis_store.save_message(
        "user1",
        "sess1",
        Message(role="user", content="hi"),
    )
    mock_redis_client.rpush.assert_called_once()
    assert not hasattr(redis_store, "save_functions")


def test_code_executor_reset():
    ex = CodeExecutor()
    ex.defined_functions["foo"] = "def foo(): pass"
    ex.reset()
    assert ex.defined_functions == {}


def test_final_answer_exception():
    exc = FinalAnswerException("done")
    assert exc.answer == "done"
