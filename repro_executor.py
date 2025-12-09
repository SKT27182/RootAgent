from smolagents import LocalPythonExecutor

class FinalAnswerException(Exception):
    def __init__(self, answer):
        self.answer = answer

def final_answer(answer):
    print(f"DEBUG: final_answer called with {answer}")
    raise FinalAnswerException(answer)

builtins = {
    "print": print, 
    "range": range,
    "final_answer": final_answer
}

print("Initializing Executor...")
executor = LocalPythonExecutor(
    additional_authorized_imports=[],
    additional_functions=builtins
)
executor.send_tools({}) # Force merge of additional_functions

code = """
print("Testing print")
final_answer("42")
"""

print(f"Executing code:\n{code}")
try:
    res = executor(code)
    print(f"Result: {res}")
except FinalAnswerException as e:
    print(f"Caught FinalAnswerException: {e.answer}")
except Exception as e:
    print(f"Caught Exception: {type(e).__name__}: {e}")
