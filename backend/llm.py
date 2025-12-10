import json
from typing import Any, Dict, Optional, Union, Type
import litellm
from litellm import completion
from pydantic import BaseModel
from backend.config import Config
from backend.utils.logger import create_logger

logger = create_logger(__name__, level="debug")

class LLMClient:
    def __init__(self, model: str = Config.DEFAULT_MODEL, api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or Config.LLM_API_KEY

    def generate(self, messages: list, schema: Optional[Union[Dict, Type[BaseModel]]] = None, **kwargs) -> Union[str, Dict, BaseModel]:
        """
        Generates a response from the LLM. 
        If schema is provided, attempts to force JSON output (handled via prompting or provider specific features).
        """
        response_format = schema
        
        # If schema is a dict, wrap it for json_object if needed, but litellm handles pydantic models directly as response_format
        if isinstance(schema, dict):
             response_format = {"type": "json_object", "response_schema": schema}

        try:
            logger.debug(f"Generating response from model: {self.model}")
            response = completion(
                model=self.model,
                messages=messages,
                api_key=self.api_key,
                response_format=response_format,
                **kwargs
            )
            content = response.choices[0].message.content
            logger.debug(f"Raw LLM Response: {response}")
            
            if schema:
                # If it is a pydantic model class
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    try:
                        return schema.model_validate_json(content)
                    except Exception:
                         # Fallback if model returned markdown code block
                        if "```json" in content:
                            content = content.split("```json")[1].split("```")[0].strip()
                            return schema.model_validate_json(content)
                        raise
                
                # If it is a dict schema (legacy support or explicit json mode)
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
            logger.error(f"LLM Generation failed: {str(e)}")
            raise RuntimeError(f"LLM Generation failed: {str(e)}")
