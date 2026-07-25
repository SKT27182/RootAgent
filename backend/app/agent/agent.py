import json
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import inspect
from jinja2 import Template

from app.agent.constants import AUTHORIZED_IMPORTS
from app.agent.executor import CodeExecutor, FinalAnswerException
from app.agent.llm import LLMClient
from app.agent.prompts import SYSTEM_PROMPT_TEMPLATE
from app.core.config import settings
from app.models.agent import AgentStep
from app.models.chat import Message
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)


class FunctionTool:
    def __init__(self, func: Callable):
        self.func = func
        self.name = func.__name__
        self.docstring = func.__doc__ or ""
        self.signature = inspect.signature(func)

    def to_code_prompt(self) -> str:
        sig_str = str(self.signature)
        doc = self.docstring.strip()
        return f"def {self.name}{sig_str}:\n    \"\"\"{doc}\"\"\"\n"


class Agent:
    def __init__(
        self,
        model_name: str = settings.llm_model,
        api_key: Optional[str] = settings.llm_api_key or None,
        additional_functions: Optional[Dict[str, Callable]] = None,
        executor: Optional[CodeExecutor] = None,
    ):
        self.llm = LLMClient(model=model_name, api_key=api_key)
        self.executor = executor or CodeExecutor(
            additional_functions=additional_functions or {}
        )
        self.max_steps = 15
        self.tools: Dict[str, FunctionTool] = {}
        if additional_functions:
            for name, func in additional_functions.items():
                self.tools[name] = FunctionTool(func)

    def _initialize_messages(
        self,
        query: Optional[str] = None,
        history: Optional[List[Message]] = None,
        artifact_context: Optional[str] = None,
        uploaded_artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[dict]:
        template = Template(SYSTEM_PROMPT_TEMPLATE)
        system_prompt = template.render(
            authorized_imports=str(AUTHORIZED_IMPORTS),
            tools=self.tools,
            uploaded_artifacts=uploaded_artifacts or [],
        )
        messages: List[dict] = [{"role": "system", "content": system_prompt}]

        for msg in history or []:
            content = msg.content
            if content.strip().startswith("[") and (
                "type" in content or "text" in content
            ):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass
            messages.append({"role": msg.role, "content": content})

        if query:
            user_content: List[dict] = [{"type": "text", "text": query}]
            if artifact_context:
                user_content.append({"type": "text", "text": artifact_context})
            messages.append({"role": "user", "content": user_content})

        return messages

    async def _generate_step(self, messages: List[dict], **kwargs) -> AgentStep:
        response = await self.llm.agenerate(messages, schema=AgentStep, **kwargs)
        if isinstance(response, AgentStep):
            return response
        return AgentStep.model_validate(response)

    def _format_step_for_history(self, step: AgentStep) -> str:
        return step.model_dump_json()

    async def run(
        self,
        query: Optional[str] = None,
        history: Optional[List[Message]] = None,
        artifact_context: Optional[str] = None,
        uploaded_artifacts: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        messages = self._initialize_messages(
            query, history, artifact_context, uploaded_artifacts
        )
        initial_message_count = len(messages)
        step_count = 0

        while step_count < self.max_steps:
            try:
                step = await self._generate_step(messages, **kwargs)
                step_json = self._format_step_for_history(step)
                messages.append({"role": "assistant", "content": step_json})

                if step.is_final_answer:
                    answer = step.final_answer or step.thinking
                    return answer, messages[initial_message_count:]

                if step.code:
                    observation = await self.executor.execute(step.code)
                    if isinstance(observation, FinalAnswerException):
                        return str(observation.answer), messages[initial_message_count:]
                    obs_msg = f"Observation: {observation}"
                    messages.append({"role": "user", "content": obs_msg})
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Error: Provide code or set is_final_answer true with final_answer.",
                        }
                    )

                step_count += 1
            except Exception as e:
                logger.error(traceback.format_exc())
                messages.append({"role": "user", "content": f"system error: {e}"})
                step_count += 1

        return (
            "Agent reached maximum steps without a final answer.",
            messages[initial_message_count:],
        )

    async def run_stream(
        self,
        query: Optional[str] = None,
        history: Optional[List[Message]] = None,
        artifact_context: Optional[str] = None,
        uploaded_artifacts: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ):
        messages = self._initialize_messages(
            query, history, artifact_context, uploaded_artifacts
        )
        step_count = 0

        while step_count < self.max_steps:
            try:
                step = await self._generate_step(messages, **kwargs)
                step_json = self._format_step_for_history(step)
                messages.append({"role": "assistant", "content": step_json})

                if step.is_final_answer:
                    yield {
                        "type": "step",
                        "step_index": step_count,
                        "step": step.model_dump(),
                    }
                    return

                if step.code:
                    yield {
                        "type": "step",
                        "step_index": step_count,
                        "step": step.model_dump(),
                    }
                    try:
                        observation = await self.executor.execute(step.code)
                        if isinstance(observation, FinalAnswerException):
                            final_step = AgentStep(
                                thinking="",
                                code=None,
                                final_answer=str(observation.answer),
                                is_final_answer=True,
                            )
                            messages.append(
                                {"role": "assistant", "content": final_step.model_dump_json()}
                            )
                            yield {
                                "type": "step",
                                "step_index": step_count + 1,
                                "step": final_step.model_dump(),
                            }
                            return
                        obs_msg = f"Observation: {observation}"
                    except Exception as exc:
                        logger.error(traceback.format_exc())
                        obs_msg = f"Execution error: {exc}"
                    messages.append({"role": "user", "content": obs_msg})
                    yield {
                        "type": "tool",
                        "step_index": step_count,
                        "content": obs_msg,
                    }
                else:
                    err = "Error: Provide code or set is_final_answer true with final_answer."
                    messages.append({"role": "user", "content": err})
                    yield {
                        "type": "step",
                        "step_index": step_count,
                        "step": step.model_dump(),
                    }
                    yield {
                        "type": "tool",
                        "step_index": step_count,
                        "content": err,
                    }

                step_count += 1

            except Exception as e:
                logger.error(traceback.format_exc())
                messages.append({"role": "user", "content": str(e)})
                step_count += 1

        yield {
            "type": "step",
            "step_index": step_count,
            "step": AgentStep(
                thinking="",
                final_answer="Agent reached maximum steps without a final answer.",
                is_final_answer=True,
            ).model_dump(),
        }
