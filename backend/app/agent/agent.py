import json
import traceback
from typing import List, Optional
from backend.app.agent.llm import LLMClient
from backend.app.agent.constants import AUTHORIZED_IMPORTS
from backend.app.agent.executor import CodeExecutor, FinalAnswerException
from backend.app.agent.prompts import SYSTEM_PROMPT_TEMPLATE
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger
from jinja2 import Template
import re
logger = create_logger(__name__, level=Config.LOG_LEVEL)

class Agent:
    def __init__(self, model_name: str = Config.DEFAULT_MODEL, api_key: Optional[str] = None):
        self.llm = LLMClient(model=model_name, api_key=api_key)
        self.executor = CodeExecutor()
        self.buffer = []  # Document history
        self.max_steps = 15

    def _initialize_messages(self, query: str, images: Optional[List[str]] = None, csv_data: Optional[str] = None) -> List[dict]:
        """Initialize the conversation messages."""
        authorized_imports = str(AUTHORIZED_IMPORTS)
        # Render system prompt
        template = Template(SYSTEM_PROMPT_TEMPLATE)
        system_prompt = template.render(
            authorized_imports=authorized_imports,
            tools={},
            managed_agents={},
            code_block_opening_tag="```python",
            code_block_closing_tag="```"
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        user_content = [{"type": "text", "text": query}]
        
        if images:
            for img_str in images:
                if not img_str.startswith("data:image"):
                    url = f"data:image/jpeg;base64,{img_str}"
                else:
                    url = img_str
                
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })
        
        if csv_data:
            import uuid
            filename = f"data_{uuid.uuid4().hex[:8]}.csv"
            with open(filename, "w") as f:
                f.write(csv_data)
            
            user_content.append({
                "type": "text",
                "text": f"\n\nI have provided a CSV file named '{filename}' containing the data. You can write code to read and analyze it."
            })
            
        messages.append({"role": "user", "content": user_content})
        return messages

    def _generate_step(self, messages: List[dict], **kwargs) -> str:
        """Call LLM and return raw string response."""
        logger.debug(f"Calling LLM with messages: {json.dumps(messages, default=str)}")
        
        response = self.llm.generate(
            messages, 
            schema=None, # Disable JSON schema enforcement
            **kwargs
        )
        
        return str(response)

    def _parse_step(self, response_text: str) -> dict:
        """
        Parse the text response to extract Thought and Code.
        Returns a dict with keys: 'thought', 'code', 'is_final_answer'
        """
        # Look for code block
        code_pattern = re.compile(r"```python(.*?)```", re.DOTALL)
        code_match = code_pattern.search(response_text)
        
        step_data = {"thought": "", "code": None}
        
        if code_match:
            step_data["code"] = code_match.group(1).strip()
            # Everything before code block is thought (loosely)
            step_data["thought"] = response_text[:code_match.start()].strip()
        else:
            step_data["thought"] = response_text.strip()
            
        return step_data

    def run(self, query: str, images: Optional[List[str]] = None, csv_data: Optional[str] = None, user_id: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> str:
        """
        Main ReAct loop.
        """
        logger.info(f"Starting session for user={user_id}, session={session_id}")
        logger.debug(f"Query: {query}")
        
        messages = self._initialize_messages(query, images, csv_data)
        
        step_count = 0
        while step_count < self.max_steps:
            try:
                # 1. Generate Step (Raw Text)
                llm_response = self._generate_step(messages, **kwargs)
                logger.debug(f"LLM Response: {llm_response}")
                
                # Append assistant message
                messages.append({"role": "assistant", "content": llm_response})
                
                # 2. Parse Step
                step_data = self._parse_step(llm_response)
                logger.info(f"--- Step {step_count} ---")
                if step_data["thought"]:
                    logger.info(f"Thought: {step_data['thought']}")
                
                # 3. Handle Code Execution
                if step_data["code"]:
                    logger.info(f"Executing Code Block:\n{step_data['code']}")
                    observation = self.executor.execute(step_data["code"])


                    logger.info(f"Observation: {observation}")
                    
                    # Check if it returned a FinalAnswerException
                    if isinstance(observation, FinalAnswerException):
                        return str(observation.answer)
                        
                    
                    # Truncate observation if too long? For now keep it simple.
                    obs_msg = f"Observation: {observation}"
                    messages.append({"role": "user", "content": obs_msg})
                else:
                    # If no code, maybe it's just a thought or the model failed to format code.
                    # We can prompt it to continue or check if it thinks it's done.
                    # But usually the loop relies on code execution to progress.
                    # If it just output text without code, we treat it as a thought and let it continue?
                    # Or we might need to nudge it. 
                    # For now, let's just append "Proceed" if provided no code, or maybe the model is just chatting.
                    if "Final Answer" in step_data["thought"]:
                         # Fallback if model just writes "Final Answer: ..." without code
                         # But the prompt strict instruction is to use final_answer tool.
                         pass
                    
                    # If we didn't execute code, we should probably just loop again?
                    # But without new user input (Observation), the model might repeat itself.
                    # So we push a dummy message? Or just rely on self-reflection?
                    messages.append({"role": "user", "content": "Proceed"})
                
                step_count += 1
                
            except Exception:
                logger.error(f"Error in step {step_count}: {traceback.format_exc()}")
                messages.append({"role": "user", "content": f"system error: {traceback.format_exc()}"})
                step_count += 1
                
        return "Agent reached maximum steps without a final answer."
