
import sys
import os

sys.path.append(os.getcwd())
from backend.app.agent.executor import CodeExecutor

def test_imports():
    print("Initializing CodeExecutor...")
    executor = CodeExecutor()
    
    print("\n--- Step 1: Define function with import ---")
    # This step defines a function 'calculate' that uses 'math'.
    # It also imports 'math'.
    code1 = """
import math
def calculate(x):
    return math.sqrt(x)
print(calculate(16))
"""
    executor.execute(code1)
    
    print("\n--- Step 2: Call function in new step ---")
    # In this step, we just call 'calculate'.
    # If 'math' was not captured/injected, 'calculate' might fail if the environment was reset 
    # and only the function def was injected without the import.
    code2 = "print(calculate(25))"
    try:
        executor.execute(code2)
    except Exception as e:
        print(f"Step 2 Failed: {e}")

if __name__ == "__main__":
    test_imports()
