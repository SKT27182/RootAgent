import json
import traceback
from typing import List, Optional
from src.llm import LLMClient
from src.executor import CodeExecutor, FinalAnswerException
from src.schema import AgentStep, Thought, Plan, CodeBlob, FinalAnswer
from src.prompts import SYSTEM_PROMPT
from src.config import Config

class Agent:
    def __init__(self, model_name: str = Config.DEFAULT_MODEL, api_key: Optional[str] = None, verbose: bool = False):
        self.llm = LLMClient(model=model_name, api_key=api_key)
        self.executor = CodeExecutor()
        self.buffer = []  # Document history
        self.max_steps = 15
        self.verbose = verbose

    def run(self, query: str, images: Optional[List[str]] = None, csv_data: Optional[str] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> str:
        """
        Main ReAct loop.
        :param query: The text query.
        :param images: List of base64 encoded image strings (with or without data prefix).
        :param csv_data: Raw CSV string content.
        :param user_id: User identifier for session tracking.
        :param session_id: Session identifier.
        """
        if self.verbose:
            print(f"Starting session for user={user_id}, session={session_id}")
        # Initialize conversation
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        user_content = [{"type": "text", "text": query}]
        
        if images:
            for img_str in images:
                # Ensure data URI format if not present, though LiteLLM often handles it.
                # Assuming base64 string.
                if not img_str.startswith("data:image"):
                    url = f"data:image/jpeg;base64,{img_str}"
                else:
                    url = img_str
                
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })
        
        if csv_data:
            # We treat CSV data by telling the agent it has access to it.
            # We can also save it to a file so code can read it.
            import uuid
            filename = f"data_{uuid.uuid4().hex[:8]}.csv"
            with open(filename, "w") as f:
                f.write(csv_data)
            
            user_content.append({
                "type": "text",
                "text": f"\n\nI have provided a CSV file named '{filename}' containing the data. You can write code to read and analyze it."
            })
            
        messages.append({"role": "user", "content": user_content})
        
        step_count = 0
        while step_count < self.max_steps:
            # 1. Call LLM
            # We want strict JSON.
            try:
                # Pass the Pydantic class directly
                # Disable reasoning for OpenRouter/Nova compatibility
                response_obj = self.llm.generate(
                    messages, 
                    schema=AgentStep,
                    extra_body={"reasoning": {"effort": "none"}}
                )
                
                # Convert back to dict for existing logic compatibility
                if hasattr(response_obj, 'model_dump'):
                    response_json = response_obj.model_dump()
                else:
                    response_json = response_obj
                
                # If wrapped in 'step' key or not, handle both if pydantic didn't handle it.
                # Our prompt asks for: {"step": {...}}
                # But AgentStep model has 'step' field, so model_dump will return {"step": {...}}
                
                if isinstance(response_json, dict) and "step" in response_json:
                    step_data = response_json["step"]
                else:
                    # Fallback or error
                    step_data = response_json
                
                # Append assistant message
                # Use model_dump_json if available for cleaner string serialization
                if hasattr(response_obj, 'model_dump_json'):
                    msg_content = response_obj.model_dump_json()
                else:
                    msg_content = json.dumps(response_json)
                    
                messages.append({"role": "assistant", "content": msg_content})
                
                step_type = step_data.get("type")
                
                if self.verbose:
                    print(f"--- Step {step_count}: {step_type} ---")
                
                if step_type == "final_answer":
                    return step_data.get("answer")
                
                elif step_type == "code":
                    code = step_data.get("code")
                    if code:
                        if self.verbose:
                            print(f"Executing Code:\n{code}")
                        observation = self.executor.execute(code)
                        
                        # Check for FinalAnswer signal
                        if isinstance(observation, FinalAnswerException):
                            return str(observation.answer)
                            
                        if self.verbose:
                            print(f"Observation: {observation}")
                        
                        # Append observation map to user role or tool role depending on API, 
                        # but standard chat is usually user role for tool outputs in simple setups
                        # or specifically 'tool' role. We'll use 'user' for simplicity with "Observation: " prefix
                        messages.append({"role": "user", "content": f"Observation: {observation}"})
                
                elif step_type in ["thought", "plan"]:
                    # Just reasoning, continue
                    if self.verbose:
                        print(f"Reasoning: {step_data.get('content')}")
                    # Append a user message to avoid "Assistant prefill" error on next turn if reasoning is used
                    messages.append({"role": "user", "content": "Proceed"})
                
                step_count += 1
                
            except Exception:
                if self.verbose:
                    print(f"Error in step {step_count}: {traceback.format_exc()}")
                # Provide feedback to agent?
                messages.append({"role": "user", "content": f"Error parsing your previous response: {traceback.format_exc()}. Please ensure valid JSON."})
                step_count += 1
                
        return "Agent reached maximum steps without a final answer."
