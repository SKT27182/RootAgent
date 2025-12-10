
import pytest
import json
import sys
import os
from unittest.mock import MagicMock, patch

# Ensure backend can be imported
sys.path.append(os.getcwd())

from backend.app.agent.agent import Agent
from backend.app.agent.executor import CodeExecutor, FinalAnswerException
from backend.app.agent.constants import AUTHORIZED_IMPORTS

@pytest.fixture
def agent():
    # Mock LLMClient to prevent actual API calls
    with patch("backend.app.agent.agent.LLMClient") as MockLLM:
        # Configure the mock to return a mock instance
        mock_instance = MockLLM.return_value
        # Default behavior for generate can be set here or per test
        mock_instance.generate.return_value = "Mock Response"
        
        agent = Agent()
        # Attach the mock instance to the agent for easier assertion
        agent.llm = mock_instance
        return agent

def test_agent_initialization(agent):
    assert agent.max_steps == 15
    assert isinstance(agent.executor, CodeExecutor)

def test_system_prompt_rendering(agent):
    # Check if _initialize_messages renders the prompt correctly
    messages = agent._initialize_messages("test query")
    system_content = messages[0]["content"]
    
    # Check for presence of key prompt elements
    assert "You are an expert assistant" in system_content
    # Check if imports are rendered
    assert str(AUTHORIZED_IMPORTS) in system_content
    # Check for code block tags
    assert "```python" in system_content

def test_parse_step(agent):
    # Case 1: Thought and Code
    response = "Thought: I will print hello.\n```python\nprint('hello')\n```"
    step_data = agent._parse_step(response)
    assert step_data["thought"].strip() == "Thought: I will print hello."
    assert step_data["code"] == "print('hello')"

    # Case 2: Only Thought
    response = "Thought: I am thinking."
    step_data = agent._parse_step(response)
    assert step_data["thought"] == "Thought: I am thinking."
    assert step_data["code"] is None
    
    # Case 3: Code block with text after (should be ignored or handled? prompt implementation ignores)
    response = "Thought: code.\n```python\nprint(1)\n```\nAfter text"
    # Regex grabs content inside ```python ... ```
    step_data = agent._parse_step(response)
    assert step_data["code"] == "print(1)"

def test_executor_success():
    executor = CodeExecutor()
    code = "x = 2 + 2\nprint(x)"
    # With new formatting, print goes to logs
    result = executor.execute(code)
    # logs="4\n", output=None (maybe?) or output=None 
    # smolagents usually captures print in logs
    assert "4" in result

def test_executor_final_answer():
    executor = CodeExecutor()
    code = "final_answer('done')"
    # execute() catches FinalAnswerException and returns the answer
    result = executor.execute(code)
    # It returns the exception object, so we verify type or attr
    assert isinstance(result, FinalAnswerException)
    assert result.answer == "done"

def test_executor_imports():
    executor = CodeExecutor()
    # Math is authorized. Last expression yield output
    assert executor.execute("import math; math.sqrt(4)") == "2.0"
    
    # Unsafe import (e.g. os) should fail
    # smolagents restricts imports.
    # Note: execute catches exceptions and returns error string
    result = executor.execute("import os")
    assert "ImportError" in result or "not allowed" in result or "Execution Error" in result

def test_agent_run_loop(agent):
    # Mock specific sequence for the run loop
    # Step 1: LLM returns code to calculate
    # Step 2: LLM returns final answer
    
    # We mock _generate_step to return raw strings directly to avoid mocking LLM response object wrapper logic in _generate_step if any
    # But better to mock LLM.generate returning string
    
    agent.llm.generate.side_effect = [
        "Thought: calc.\n```python\nprint(5 * 5)\n```", # Step 1
        "Thought: done.\n```python\nfinal_answer('25')\n```" # Step 2
    ]
    
    result = agent.run("calculate 5*5")
    
    assert result == "25"
    assert agent.llm.generate.call_count == 2
