from __future__ import annotations

import ast
import math
from types import ModuleType

import pytest

from app.utils.local_python_executor import (
    BASE_PYTHON_TOOLS,
    InterpreterError,
    LocalPythonExecutor,
    PrintContainer,
    check_import_authorized,
    check_safer_result,
    evaluate_ast,
    evaluate_python_code,
    fix_final_answer_code,
    get_iterable,
    get_safe_module,
    safer_func,
    truncate_content,
)


def execute(code: str, *, state: dict | None = None):
    execution_state = {} if state is None else state
    result, is_final = evaluate_python_code(
        code,
        static_tools=BASE_PYTHON_TOOLS,
        state=execution_state,
    )
    return result, is_final, execution_state


def test_interpreter_handles_control_flow_functions_and_unpacking() -> None:
    result, is_final, state = execute(
        """
def calculate(base, increment=2):
    total = base + increment
    for value in [-1, 5]:
        if value < 0:
            continue
        total += value
        if total > 10:
            break
    return total

def count_arguments(*extra, **options):
    return len(extra) + len(options)

values = (3, 4)
left, right = values
answer = calculate(left, right)
argument_count = count_arguments(1, 2, enabled=True)
label = 'large' if answer >= 10 else 'small'
print(f'{label}:{answer:02d}')
(answer, label, argument_count)
"""
    )

    assert result == (12, "large", 3)
    assert is_final is False
    assert str(state["_print_outputs"]) == "large:12\n"


def test_interpreter_handles_collections_comprehensions_and_slices() -> None:
    result, _, state = execute(
        """
numbers = [1, 2, 3, 4, 5]
squares = [value * value for value in numbers if value % 2 == 1]
pairs = {(left, right) for left in [1, 2] for right in [3, 4]}
generated = sum(value for value in numbers if value > 2)
mapping = {'first': squares[0], 'last': squares[-1]}
window = numbers[1:5:2]
del mapping['first']
del numbers[0]
(squares, pairs, generated, mapping, window, numbers)
"""
    )

    assert result == (
        [1, 9, 25],
        {(1, 3), (1, 4), (2, 3), (2, 4)},
        12,
        {"last": 25},
        [2, 4],
        [2, 3, 4, 5],
    )
    assert state["generated"] == 12


def test_interpreter_handles_while_try_raise_assert_and_finally() -> None:
    result, _, state = execute(
        """
counter = 0
events = []
while counter < 5:
    counter += 1
    if counter == 2:
        continue
    events += [counter]
    if counter == 4:
        break

try:
    raise ValueError('expected')
except ValueError as error:
    events += [str(error)]
else:
    events += ['unexpected']
finally:
    events += ['finished']

assert counter == 4, 'loop did not stop'
events
"""
    )

    assert result == [1, 3, 4, "expected", "finished"]
    assert state["counter"] == 4


def test_interpreter_handles_classes_annotations_and_attributes() -> None:
    result, _, _ = execute(
        """
class Counter:
    'A small stateful counter.'
    category: str = 'example'

    def __init__(self, start: int):
        self.value = start

    def add(self, amount=1):
        self.value += amount
        return self.value

counter = Counter(4)
first = counter.add()
second = counter.add(3)
(first, second, counter.category)
"""
    )

    assert result == (5, 8, "example")


def test_interpreter_imports_authorized_modules_and_aliases() -> None:
    result, _, _ = execute(
        """
import math as mathematics
from statistics import mean as average
(mathematics.sqrt(81), average([2, 4, 6]))
"""
    )

    assert result == (9.0, 4)


def test_executor_preserves_state_tools_variables_and_final_answer() -> None:
    executor = LocalPythonExecutor(
        additional_authorized_imports=[],
        max_print_outputs_length=12,
        additional_functions={"double": lambda value: value * 2},
    )
    executor.send_tools({"final_answer": lambda value: {"answer": value}})
    executor.send_variables({"seed": 5})

    first = executor("value = double(seed)\nprint('abcdefghijklmno')\nvalue")
    final = executor("final_answer(value + 1)")

    assert first.output == 10
    assert "truncated" in first.logs
    assert first.is_final_answer is False
    assert final.output == {"answer": 11}
    assert final.is_final_answer is True


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("missing_name", "not defined"),
        ("import os", "Import of os is not allowed"),
        ("print = 1", "erase the existing tool"),
        ("(1).__class__", "Forbidden access to dunder attribute"),
        ("items = [1]\nitems[3]", "Could not index"),
        ("assert False, 'bad value'", "bad value"),
        ("del absent", "Cannot delete name"),
        ("for", "Code parsing failed"),
    ],
)
def test_interpreter_reports_safe_contextual_errors(code: str, message: str) -> None:
    with pytest.raises(InterpreterError, match=message):
        execute(code)


def test_interpreter_helper_safety_and_formatting_paths() -> None:
    assert truncate_content("short", 10) == "short"
    assert "truncated" in truncate_content("0123456789abcdef", 8)
    assert get_iterable([1, 2]) == [1, 2]
    assert get_iterable((1, 2)) == [1, 2]
    with pytest.raises(InterpreterError, match="not iterable"):
        get_iterable(1)

    code = "final_answer = 3\nfinal_answer(final_answer)"
    fixed = fix_final_answer_code(code)
    assert "final_answer_variable = 3" in fixed
    assert "final_answer(final_answer_variable)" in fixed
    assert fix_final_answer_code("final_answer = 3") == "final_answer = 3"

    assert check_import_authorized("math", ["math"])
    assert check_import_authorized("package.child", ["package.*"])
    assert not check_import_authorized("os", ["math"])


def test_interpreter_safe_result_and_wrapper_reject_dangerous_values() -> None:
    check_safer_result(math, authorized_imports=["math"])
    with pytest.raises(InterpreterError, match="Forbidden access to module"):
        check_safer_result(math, authorized_imports=["statistics"])
    with pytest.raises(InterpreterError, match="Forbidden access to function"):
        check_safer_result(eval, authorized_imports=[])

    wrapped = safer_func(lambda: math, authorized_imports=["statistics"])
    with pytest.raises(InterpreterError, match="Forbidden access to module"):
        wrapped()
    assert safer_func(int) is int


def test_print_container_and_safe_module_behave_like_runtime_values() -> None:
    output = PrintContainer()
    output.append("one")
    output += 2
    assert str(output) == "one2"
    assert repr(output) == "PrintContainer(one2)"
    assert len(output) == 4

    safe_math = get_safe_module(math, ["math"])
    assert isinstance(safe_math, ModuleType)
    assert safe_math.sqrt(16) == 4
    marker = object()
    assert get_safe_module(marker, []) is marker


def test_direct_ast_evaluation_covers_supported_operators() -> None:
    state: dict = {"_print_outputs": PrintContainer()}
    tools = BASE_PYTHON_TOOLS.copy()
    custom: dict = {}

    for source, expected in [
        ("-3", -3),
        ("+3", 3),
        ("not True", False),
        ("~1", -2),
        ("7 // 2", 3),
        ("7 % 4", 3),
        ("2 ** 3", 8),
        ("6 & 3", 2),
        ("4 | 1", 5),
        ("7 ^ 2", 5),
        ("1 << 3", 8),
        ("8 >> 2", 2),
        ("1 < 2 <= 2", True),
        ("1 != 2 and 2 in [1, 2]", True),
    ]:
        node = ast.parse(source, mode="eval").body
        assert evaluate_ast(node, state, tools, custom) == expected
