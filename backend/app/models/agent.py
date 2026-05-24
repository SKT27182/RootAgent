from typing import Optional

from pydantic import BaseModel, Field


class AgentStep(BaseModel):
    """Structured JSON step from the LLM."""

    thinking: str = Field(..., description="Reasoning for this step.")
    code: Optional[str] = Field(None, description="Python code to execute.")
    final_answer: Optional[str] = Field(
        None, description="User-visible answer when is_final_answer is true."
    )
    is_final_answer: bool = Field(
        False, description="Whether this step ends the task."
    )


class AgentObservation(BaseModel):
    output: str
    error: Optional[str] = None
