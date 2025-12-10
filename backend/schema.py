from typing import List, Union, Optional, Literal
from pydantic import BaseModel, Field

class Thought(BaseModel):
    """Represents a reasoning step where the agent thinks about the problem."""
    type: Literal["thought"] = "thought"
    content: str = Field(..., description="The reasoning content.")

class Plan(BaseModel):
    """Represents the plan of action."""
    type: Literal["plan"] = "plan"
    steps: List[str] = Field(..., description="List of steps to execute.")

class CodeBlob(BaseModel):
    """Represents a block of code to be executed."""
    type: Literal["code"] = "code"
    language: str = Field("python", description="The programming language.")
    code: str = Field(..., description="The raw code to execute.")

class FinalAnswer(BaseModel):
    """Represents the final answer to the user's query."""
    type: Literal["final_answer"] = "final_answer"
    answer: str = Field(..., description="The final answer text.")

class AgentStep(BaseModel):
    """Union of all possible agent steps."""
    step: Union[Thought, Plan, CodeBlob, FinalAnswer]

class Observation(BaseModel):
    """Represents the result of an execution or external event."""
    type: Literal["observation"] = "observation"
    content: str = Field(..., description="The observation content.")
