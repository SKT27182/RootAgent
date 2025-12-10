import json
import traceback
from typing import List, Optional
from backend.app.agent.llm import LLMClient
from backend.app.agent.executor import CodeExecutor, FinalAnswerException
from backend.app.agent.schema import AgentStep, Thought, Plan, CodeBlob, FinalAnswer
from backend.app.agent.prompts import SYSTEM_PROMPT
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger
logger = create_logger(__name__, level=Config.LOG_LEVEL)

class Agent:
    def __init__(self, model_name: str = Config.DEFAULT_MODEL, api_key: Optional[str] = None):
        self.llm = LLMClient(model=model_name, api_key=api_key)
        self.executor = CodeExecutor()
        self.buffer = []  # Document history
        self.max_steps = 15

    def _initialize_messages(self, query: str, images: Optional[List[str]] = None, csv_data: Optional[str] = None) -> List[dict]:
        """Initialize the conversation messages."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
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

    def _generate_step(self, messages: List[dict], **kwargs) -> dict:
        """Call LLM and allow Pydantic validation."""
        logger.debug(f"Calling LLM with messages: {json.dumps(messages, default=str)}")
        
        response_obj = self.llm.generate(
            messages, 
            schema=AgentStep,
            **kwargs
        )
        
        # Convert Pydantic object to dict
        if hasattr(response_obj, 'model_dump'):
            response_json = response_obj.model_dump()
        else:
            response_json = response_obj
        
        # Extract 'step' data
        if isinstance(response_json, dict) and "step" in response_json:
            step_data = response_json["step"]
        else:
            step_data = response_json
            
        logger.debug(f"Parsed Step Data: {step_data}")
        return step_data, response_obj

    def _handle_code_step(self, step_data: dict) -> str:
        """Execute code and return observation."""
        code = step_data.get("code")
        if code:
            logger.debug(f"Executing Code:\n{code}")
            observation = self.executor.execute(code)
            
            # Check for FinalAnswer signal (return as string or exception object handled by caller?)
            # The original logic handled exception return. Here we return the object/string.
            return observation
        return "No code provided."

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
                # 1. Generate Step
                step_data, response_obj = self._generate_step(messages, **kwargs)
                
                # Append assistant message
                if hasattr(response_obj, 'model_dump_json'):
                    msg_content = response_obj.model_dump_json()
                else:
                    msg_content = json.dumps(response_obj.model_dump() if hasattr(response_obj, 'model_dump') else response_obj)
                    
                messages.append({"role": "assistant", "content": msg_content})
                
                step_type = step_data.get("type")
                logger.info(f"--- Step {step_count}: {step_type} ---")
                
                # 2. Handle Step Type
                if step_type == "final_answer":
                    return step_data.get("answer")
                
                elif step_type == "code":
                    observation = self._handle_code_step(step_data)
                    
                    if isinstance(observation, FinalAnswerException):
                        return str(observation.answer)
                        
                    logger.debug(f"Observation: {observation}")
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                
                elif step_type in ["thought", "plan"]:
                    logger.info(f"Reasoning: {step_data.get('content')}")
                    # Append a user message to avoid "Assistant prefill" error
                    messages.append({"role": "user", "content": "Proceed"})
                
                step_count += 1
                
            except Exception:
                logger.error(f"Error in step {step_count}: {traceback.format_exc()}")
                messages.append({"role": "user", "content": f"Error parsing your previous response: {traceback.format_exc()}. Please ensure valid JSON."})
                step_count += 1
                
        return "Agent reached maximum steps without a final answer."
