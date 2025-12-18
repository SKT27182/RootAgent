import pytest
import json
import uuid
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock, ANY
from typing import List

# Ensure backend can be imported
sys.path.append(os.getcwd())

from backend.app.agent.agent import Agent, FunctionTool
from backend.app.agent.executor import CodeExecutor, FinalAnswerException
from backend.app.agent.constants import AUTHORIZED_IMPORTS
from backend.app.services.redis_store import RedisStore
from backend.app.models.chat import Message
from backend.app.models.agent import AgentStep
from backend.app.agent.llm import LLMClient

# =================================================================================================
# RedisStore Tests
# =================================================================================================


@pytest.fixture
def mock_redis_client():
    mock = AsyncMock()
    # Mock return values for common methods as needed
    mock.rpush.return_value = 1
    mock.lrange.return_value = []
    return mock


@pytest.fixture
def redis_store(mock_redis_client):
    with patch(
        "backend.app.services.redis_store.redis.Redis", return_value=mock_redis_client
    ):
        # We need to bypass the __init__ connection attempt if it's real
        # But we are mocking redis.Redis so it should be fine.
        store = RedisStore(host="localhost", port=6379)
        # Ensure our mock client is the one being used (in case logic changes)
        store.redis_client = mock_redis_client
        return store


@pytest.mark.anyio
async def test_redis_save_message(redis_store, mock_redis_client):
    user_id = "u1"
    session_id = "s1"
    message = Message(role="user", content="hello", message_id="m1")

    await redis_store.save_message(user_id, session_id, message)

    key = redis_store._get_session_key(user_id, session_id)
    mock_redis_client.rpush.assert_called_once()
    # Check arguments: key, json_string
    call_args = mock_redis_client.rpush.call_args
    assert call_args[0][0] == key
    assert "hello" in call_args[0][1]


@pytest.mark.anyio
async def test_redis_get_session_history(redis_store, mock_redis_client):
    user_id = "u1"
    session_id = "s1"
    key = redis_store._get_session_key(user_id, session_id)

    # Mock data in Redis
    msg1 = Message(role="user", content="hi", message_id="m1")
    msg2 = Message(role="assistant", content="hello", message_id="m2")
    mock_redis_client.lrange.return_value = [
        msg1.model_dump_json(),
        msg2.model_dump_json(),
    ]

    history = await redis_store.get_session_history(user_id, session_id)

    mock_redis_client.lrange.assert_called_once_with(key, 0, -1)
    assert len(history) == 2
    assert history[0].content == "hi"
    assert history[1].content == "hello"


@pytest.mark.anyio
async def test_redis_clear_session(redis_store, mock_redis_client):
    user_id = "u1"
    session_id = "s1"
    key = redis_store._get_session_key(user_id, session_id)

    await redis_store.clear_session(user_id, session_id)

    # Needs to verify calls to delete
    # Based on implementation: deletes key and key:functions
    assert mock_redis_client.delete.call_count >= 1
    mock_redis_client.delete.assert_any_call(key)
    mock_redis_client.delete.assert_any_call(f"{key}:functions")


@pytest.mark.anyio
async def test_redis_save_get_functions(redis_store, mock_redis_client):
    user_id = "u1"
    session_id = "s1"
    functions = {"foo": "def foo(): pass"}

    # Test Save
    await redis_store.save_functions(user_id, session_id, functions)
    key = f"{redis_store._get_session_key(user_id, session_id)}:functions"
    mock_redis_client.hset.assert_called_once_with(key, mapping=functions)

    # Test Get
    mock_redis_client.hgetall.return_value = functions
    retrieved = await redis_store.get_functions(user_id, session_id)
    mock_redis_client.hgetall.assert_called_once_with(key)
    assert retrieved["foo"] == "def foo(): pass"


@pytest.mark.anyio
async def test_redis_save_get_imports(redis_store, mock_redis_client):
    user_id = "u1"
    session_id = "s1"
    imports = {"import math", "import os"}

    # Test Save
    await redis_store.save_imports(user_id, session_id, imports)
    key = f"{redis_store._get_session_key(user_id, session_id)}:imports"
    mock_redis_client.sadd.assert_called_once_with(key, *imports)

    # Test Get
    mock_redis_client.smembers.return_value = imports
    retrieved = await redis_store.get_imports(user_id, session_id)
    mock_redis_client.smembers.assert_called_once_with(key)
    assert "import math" in retrieved


# =================================================================================================
# Agent Tests
# =================================================================================================


@pytest.fixture
def agent():
    # Mock LLMClient to prevent actual API calls
    with patch("backend.app.agent.agent.LLMClient") as MockLLM:
        mock_instance = MockLLM.return_value
        # Default behavior for generate
        mock_instance.agenerate = AsyncMock(return_value="Mock Response")

        agent = Agent()
        return agent


## Actual llm call test
@pytest.mark.anyio
@pytest.mark.llm
async def test_llm_agenerate_real_call():
    llm = LLMClient()
    messages = [
        {"role": "system", "content": "You are a precise assistant."},
        {"role": "user", "content": "Reply with exactly the word: OK"},
    ]
    response = await llm.agenerate(messages)
    assert isinstance(response, str)
    assert "OK" in response.strip()


def test_agent_initialization_with_previous_state():
    previous_funcs = {"my_func": "def my_func(): return 10"}
    previous_imports = {"import math"}

    with patch("backend.app.agent.agent.LLMClient"):
        agent = Agent(
            previous_functions=previous_funcs, previous_imports=previous_imports
        )

        # Check executor state
        assert "my_func" in agent.executor.defined_functions
        assert "import math" in agent.executor.defined_imports

        # Verify function is actually callable in executor
        assert agent.executor.execute("my_func()") == "10"


def test_initialize_messages_structure(agent):
    query = "do something"
    messages = agent._initialize_messages(query=query)

    # 0: System
    # 1: User
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "You are an expert assistant" in messages[0]["content"]
    assert "math" in messages[0]["content"]

    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == [{"type": "text", "text": query}]


def test_initialize_messages_with_images(agent):
    query = "look at this"
    images = ["base64string"]
    messages = agent._initialize_messages(query=query, images=images)

    user_content = messages[1]["content"]
    assert len(user_content) == 2
    assert user_content[0] == {"type": "text", "text": query}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_initialize_messages_with_history(agent):
    history = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    messages = agent._initialize_messages(query="next", history=history)

    # System + 2 history + 1 new user
    assert len(messages) == 4
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "hi"
    assert messages[2]["role"] == "assistant"
    assert messages[2]["content"] == "hello"


def test_initialize_messages_with_csv(agent):
    # Mock open needed? uuid is generated inside.
    # The agent writes to a file. We should mock open to avoid real file creation.
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        messages = agent._initialize_messages(
            query="analyze", csv_data="col1,col2\n1,2"
        )

        # Verify file writing
        mock_open.assert_called_once()
        handle = mock_open.return_value.__enter__.return_value
        handle.write.assert_called_with("col1,col2\n1,2")

        # Verify prompt update
        user_content = messages[1]["content"]
        # It appends a text block about the CSV
        assert len(user_content) == 2
        assert "I have provided a CSV file" in user_content[1]["text"]


def test_parse_step_thought_and_code(agent):
    response = "Thought: simple.\n```python\nx=1\n```"
    step = agent._parse_step(response)
    assert step.thought.strip() == "Thought: simple."
    assert step.code == "x=1"


def test_parse_step_no_code(agent):
    response = "Thought: just thinking."
    step = agent._parse_step(response)
    assert step.thought == "Thought: just thinking."
    assert step.code is None


def test_parse_step_malformed_code(agent):
    # Missing closing tag or weird format
    # The regex is ```python(.*?)```
    response = "Thought: x\n```python\nprint(1)"
    step = agent._parse_step(response)
    # Should fail to match code, treat all as thought
    assert "print(1)" in step.thought
    assert step.code is None


@pytest.mark.anyio
async def test_run_single_step_final_answer(agent):
    # Mock LLM to return a final answer immediately
    agent.llm.agenerate.return_value = (
        "Thought: done.\n```python\nfinal_answer('result')\n```"
    )

    answer, steps = await agent.run("go")

    assert answer == "result"
    assert len(steps) >= 1  # Should contain the assistant message
    assert steps[-1]["role"] == "assistant"


@pytest.mark.anyio
async def test_run_max_steps_reached(agent):
    agent.max_steps = 2
    # Mock LLM to always return a non-final step
    agent.llm.agenerate.return_value = "Thought: loop.\n```python\nprint('loop')\n```"

    answer, steps = await agent.run("go")

    assert "maximum steps" in answer
    # Should have run 2 steps
    # Each step adds: Assistant (thought/code) + User (Observation) = 2 messages per step
    # plus initial history... wait, 'steps' return is just messages list?
    # run returns (answer, messages[initial_count:])
    # 2 steps * 2 messages = 4 messages generated
    assert len(steps) == 4


@pytest.mark.anyio
async def test_run_execution_error(agent):
    # Step 1: Code that errors
    # Step 2: Final answer
    agent.llm.agenerate = AsyncMock(
        side_effect=[
            "Thought: error.\n```python\nraise ValueError('oops')\n```",
            "Thought: fixed.\n```python\nfinal_answer('fixed')\n```",
        ]
    )

    answer, steps = await agent.run("test error")

    assert answer == "fixed"
    # Check that error was captured in observation
    observation_msg = steps[1]  # 0 is assistant, 1 is observation
    assert "ValueError: oops" in observation_msg["content"]


@pytest.mark.anyio
async def test_run_no_code_fallback(agent):
    # Step 1: No code
    # Step 2: Correct code
    agent.llm.agenerate = AsyncMock(
        side_effect=[
            "Thought: I forgot code.",
            "Thought: sorry.\n```python\nfinal_answer('ok')\n```",
        ]
    )

    answer, steps = await agent.run("test no code")

    assert answer == "ok"
    # Verify we sent a warning to the model
    # steps[0] -> assistant "Thought: I forgot code."
    # steps[1] -> user "Error: You did not provide any code block..."
    assert "Error: You did not provide any code block" in steps[1]["content"]


# =================================================================================================
# Executor Tests (Brief sanity check as separate file usually covers executor, but requested 'all possible')
# =================================================================================================


def test_executor_authorized_imports():
    executor = CodeExecutor()
    # Should allow math
    res = executor.execute("import math\nmath.sqrt(4)")
    assert "2.0" in str(res)


def test_executor_blocked_import():
    executor = CodeExecutor()
    res = executor.execute("import os")
    assert "ImportError" in str(res) or "not allowed" in str(res)
