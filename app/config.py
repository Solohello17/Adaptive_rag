from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Provider Selection
    LLM_PROVIDER: str = "gemini"
    LLM_PROVIDER_FAST: str = "groq"
    EMBEDDINGS_PROVIDER: str = "local"
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "meta/llama-3.1-70b-instruct"
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "meta-llama/llama-3.1-8b-instruct:free"
    OPENROUTER_SITE_URL: str = "http://localhost:8000"
    OPENROUTER_APP_NAME: str = "Adaptive RAG"

    # Database Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    MONGODB_URI: str = "mongodb://localhost:27017"
    
    class Config:
        env_file = ".env"

settings = Settings()
