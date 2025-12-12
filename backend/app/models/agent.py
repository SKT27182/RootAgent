from typing import Optional, Literal
from pydantic import BaseModel, Field


class AgentStep(BaseModel):
    """
    Represents a single step in the Agent's reasoning loop.
    """

    thought: str = Field(..., description="The reasoning thought process.")
    code: Optional[str] = Field(None, description="The code block to execute.")
    is_final_answer: bool = Field(
        False, description="Whether this step contains the final answer."
    )


class AgentObservation(BaseModel):
    """
    Represents the output/observation from executing a code block.
    """

    output: str
    error: Optional[str] = None
