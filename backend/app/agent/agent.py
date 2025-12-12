import json
import traceback
from typing import List, Optional, Callable, Dict, Set, Tuple, Any
import inspect
from backend.app.agent.llm import LLMClient
from backend.app.models.chat import Message
from backend.app.agent.constants import (
    AUTHORIZED_IMPORTS,
    CODE_BLOCK_OPENING_TAG,
    CODE_BLOCK_CLOSING_TAG,
)
from backend.app.agent.executor import CodeExecutor, FinalAnswerException
from backend.app.agent.prompts import SYSTEM_PROMPT_TEMPLATE
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger
from backend.app.models.agent import AgentStep
from jinja2 import Template
import re
import uuid

logger = create_logger(__name__, level=Config.LOG_LEVEL)


class FunctionTool:
    def __init__(self, func: Callable):
        self.func = func
        self.name = func.__name__
        self.docstring = func.__doc__ or ""
        self.signature = inspect.signature(func)

    def to_code_prompt(self) -> str:
        """
        Generates a string representation of the function for the prompt.
        Format:
        def function_name(args) -> return_type:
            \"\"\"
            docstring
            \"\"\"
        """
        # Get source code of the signature line
        try:
            # This is a bit tricky, inspect.getsource might return the whole function.
            # We construct it from signature
            sig_str = str(self.signature)
            # Add type hints if available? They are in signature.

        except Exception:
            sig_str = "(...)"

        return f'def {self.name}{sig_str}:\n    """\n    {self.docstring.strip()}\n    """\n'


class Agent:
    def __init__(
        self,
        model_name: str = Config.DEFAULT_MODEL,
        api_key: Optional[str] = None,
        additional_functions: Optional[Dict[str, Callable]] = {},
        previous_functions: Dict[str, str] = {},
        previous_imports: Set[str] = set(),
    ):
        self.llm = LLMClient(model=model_name, api_key=api_key)

        self.executor = CodeExecutor(additional_functions=additional_functions)

        injected_code = ""

        # Inject imports
        if previous_imports:
            injected_code += "\n".join(previous_imports) + "\n\n"

        (
            logger.debug(f"Injected imports: {previous_imports}")
            if previous_imports
            else logger.debug("No previous imports")
        )
        # Inject functions
        for func_name, func_source in previous_functions.items():
            injected_code += func_source + "\n\n"

        self.executor.execute(injected_code)
        (
            logger.debug(
                f"Injected Previously defined functions: {list(self.executor.defined_functions.keys())}"
            )
            if previous_functions
            else logger.debug("No previous function definitions")
        )

        self.executor.defined_functions.update(previous_functions)
        self.executor.defined_imports.update(previous_imports)

        self.buffer = []  # Document history
        self.max_steps = 15

        self.tools = {}

        # Tools standard (passed in init from server code)
        if additional_functions:
            for name, func in additional_functions.items():
                self.tools[name] = FunctionTool(func)

    def get_all_defined_functions(self) -> Tuple[Set[str], Dict[str, str]]:
        """
        Returns all functions defined during the session (previous + new).
        """
        return self.executor.defined_imports, self.executor.defined_functions

    def _initialize_messages(
        self,
        query: Optional[str] = None,
        history: List[Message] = [],
        images: Optional[List[str]] = None,
        csv_data: Optional[str] = None,
    ) -> List[dict]:
        """Initialize the conversation messages."""
        authorized_imports = str(AUTHORIZED_IMPORTS)
        # Render system prompt
        template = Template(SYSTEM_PROMPT_TEMPLATE)
        system_prompt = template.render(
            authorized_imports=authorized_imports,
            tools=self.tools,
            self_defined_functions=self.executor.defined_functions,
            managed_agents={},
            code_block_opening_tag=CODE_BLOCK_OPENING_TAG,
            code_block_closing_tag=CODE_BLOCK_CLOSING_TAG,
        )

        messages = [{"role": "system", "content": system_prompt}]

        # Add history
        for msg in history:
            content = msg.content
            # Check if content is a list of dicts serialized as JSON string
            if content.strip().startswith("[") and (
                "type" in content or "text" in content
            ):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass  # Keep as string if parsing fails

            messages.append({"role": msg.role, "content": content})

        # If query is provided, format it as a new user message (legacy/direct call support)
        # If query is None, we assume the latest message in history is the user's input.
        if query:
            user_content = [{"type": "text", "text": query}]

            if images:
                for img_str in images:
                    if not img_str.startswith("data:image"):
                        url = f"data:image/jpeg;base64,{img_str}"
                    else:
                        url = img_str

                    user_content.append(
                        {"type": "image_url", "image_url": {"url": url}}
                    )

            if csv_data:
                filename = f"data_{uuid.uuid4().hex[:8]}.csv"
                with open(filename, "w") as f:
                    f.write(csv_data)

                user_content.append(
                    {
                        "type": "text",
                        "text": f"\n\nI have provided a CSV file named '{filename}' containing the data. You can write code to read and analyze it.",
                    }
                )

            messages.append({"role": "user", "content": user_content})

        return messages

    async def _generate_step(self, messages: List[dict], **kwargs) -> str:
        """Call LLM and return raw string response."""
        logger.debug(f"Calling LLM with messages: {json.dumps(messages, default=str)}")

        response = await self.llm.agenerate(
            messages, schema=None, **kwargs  # Disable JSON schema enforcement
        )

        return str(response)

    def _parse_step(self, response_text: str) -> AgentStep:
        """
        Parse the text response to extract Thought and Code.
        Returns an AgentStep object.
        """
        # Look for code block
        code_pattern = re.compile(r"```python(.*?)```", re.DOTALL)
        code_match = code_pattern.search(response_text)

        thought = ""
        code = None

        if code_match:
            code = code_match.group(1).strip()
            # Everything before code block is thought (loosely)
            thought = response_text[: code_match.start()].strip()
        else:
            thought = response_text.strip()

        return AgentStep(thought=thought, code=code)

    async def run(
        self,
        query: Optional[str] = None,
        images: Optional[List[str]] = None,
        csv_data: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        history: List[Message] = [],
        **kwargs,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Main ReAct loop.
        Returns:
            final_answer: str
            steps: List[Dict[str, Any]] - list of raw messages generated during the loop
        """
        logger.debug(f"Query: {query}")

        messages = self._initialize_messages(query, history, images, csv_data)

        # Track where the new steps start
        initial_message_count = len(messages)

        step_count = 0
        while step_count < self.max_steps:
            try:
                # 1. Generate Step (Raw Text)
                llm_response = await self._generate_step(messages, **kwargs)
                logger.debug(f"LLM Response: {llm_response}")

                # Append assistant message
                messages.append({"role": "assistant", "content": llm_response})

                # 2. Parse Step
                step_data = self._parse_step(llm_response)
                logger.info(f"--- Step {step_count} ---")
                if step_data.thought:
                    logger.info(f"Thought: {step_data.thought}")

                # 3. Handle Code Execution
                if step_data.code:
                    logger.info(f"Executing Code Block:\n{step_data.code}")
                    observation = self.executor.execute(step_data.code)

                    logger.info(f"Observation: {observation}")

                    # Check if it returned a FinalAnswerException
                    if isinstance(observation, FinalAnswerException):
                        return str(observation.answer), messages[initial_message_count:]

                    # Truncate observation if too long? For now keep it simple.
                    obs_msg = f"Observation: {observation}"
                    messages.append({"role": "user", "content": obs_msg})
                else:
                    # Fallback: if no code was found, strictly prompt for it.
                    logger.warning("No code block found in LLM response.")
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Error: You did not provide any code block. You must output code in a {CODE_BLOCK_OPENING_TAG} ... {CODE_BLOCK_CLOSING_TAG} block. If you have the answer, use `final_answer('...')` inside a code block.",
                        }
                    )

                step_count += 1

            except Exception:
                logger.error(f"Error in step {step_count}: {traceback.format_exc()}")
                messages.append(
                    {
                        "role": "user",
                        "content": f"system error: {traceback.format_exc()}",
                    }
                )
                step_count += 1

        # If we reach here without returning, check if the last message was a thought that looked like an answer
        last_thought = messages[-1].get("content", "")
        if step_count >= self.max_steps:
            return (
                "Agent reached maximum steps without a final answer.",
                messages[initial_message_count:],
            )

        return (
            "Agent finished without a final answer.",
            messages[initial_message_count:],
        )
