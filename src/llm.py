import json
from typing import Any, Dict, Optional, Union
import litellm
from litellm import completion
from src.config import Config

class LLMClient:
    def __init__(self, model: str = Config.DEFAULT_MODEL, api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or Config.LLM_API_KEY

    def generate(self, messages: list, schema: Optional[Dict] = None) -> Union[str, Dict]:
        """
        Generates a response from the LLM. 
        If schema is provided, attempts to force JSON output (handled via prompting or provider specific features).
        """
        response_format = {"type": "json_object"} if schema else None
        
        try:
            response = completion(
                model=self.model,
                messages=messages,
                api_key=self.api_key,
                response_format=response_format,
                temperature=0.0
            )
            content = response.choices[0].message.content
            
            if schema:
                # robust parsing
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # In case the model returned markdown code block
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                        return json.loads(content)
                    raise ValueError(f"Failed to parse JSON response: {content}")
            
            return content

        except Exception as e:
            raise RuntimeError(f"LLM Generation failed: {str(e)}")
