import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
DEFAULT_MODEL_NAME = "gemini/gemini-2.5-flash"

class Config:
    # API Keys
    # Prioritize generic LLM_API_KEY, then specific provider keys
    LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("HF_API_KEY")
    
    # Model Defaults
    DEFAULT_MODEL = os.environ.get("LLM_MODEL", DEFAULT_MODEL_NAME)
    
    # Validation
    @classmethod
    def validate(cls):
        if not cls.LLM_API_KEY:
            print("WARNING: No LLM_API_KEY or provider key found.")
        
        # Ensure GEMINI_API_KEY is set for LiteLLM if we have a key and using Gemini
        if cls.LLM_API_KEY and "gemini" in cls.DEFAULT_MODEL.lower():
            os.environ["GEMINI_API_KEY"] = cls.LLM_API_KEY

# Run validation on import
Config.validate()
