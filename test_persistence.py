
import sys
import os
from backend.app.agent.agent import Agent
from backend.app.services.redis_store import RedisStore
from backend.app.services.agent_manager import AgentManager
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

def test_persistence_logic():
    print("--- Starting Persistence Test ---")
    
    # 1. Simulate Turn 1: Agent defines a function
    print("\n[Step 1] Agent 1 defines a function...")
    agent1 = Agent()
    
    # Simulate execution of code that defines a function
    code_def = """
def persistent_magic(x):
    \"\"\"
    A persistent magic function.
    \"\"\"
    return x + 999
"""
    agent1.executor.execute(code_def)
    
    # Check if tracked
    if "persistent_magic" in agent1.executor.defined_functions:
        print("SUCCESS: Agent 1 tracked 'persistent_magic'.")
    else:
        print("FAILURE: Agent 1 did NOT track 'persistent_magic'.")
        return

    # 2. Simulate Saving to Redis (Mocking the data transfer)
    saved_functions = agent1.get_all_defined_functions()
    print(f"[Step 2] Saved functions: {list(saved_functions.keys())}")
    
    # 3. Simulate Turn 2: New Agent restoration
    print("\n[Step 3] Creating Agent 2 with restored functions...")
    agent2 = Agent(previous_definitions=saved_functions)
    
    # Check hydration
    if "persistent_magic" in agent2.hydrated_functions:
        print("SUCCESS: Agent 2 hydrated 'persistent_magic'.")
    else:
        print("FAILURE: Agent 2 did NOT hydrate 'persistent_magic'.")

    # Check Prompt
    msgs = agent2._initialize_messages("test")
    prompt = msgs[0]["content"]
    if "def persistent_magic(x):" in prompt:
         print("SUCCESS: Function visible in Agent 2 prompt.")
    else:
         print("FAILURE: Function NOT visible in Agent 2 prompt.")

    # 4. Execute in Agent 2
    print("\n[Step 4] Agent 2 executing the restored function...")
    execution_code = "print(persistent_magic(1))"
    result = agent2.executor.execute(execution_code)
    
    if "1000" in str(result):
        print(f"SUCCESS: Agent 2 executed persistent function. Result: {result}")
    else:
        print(f"FAILURE: Agent 2 execution failed. Result: {result}")

if __name__ == "__main__":
    test_persistence_logic()
