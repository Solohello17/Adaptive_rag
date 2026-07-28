from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Provider Selection
    LLM_PROVIDER: str = "gemini"
    EMBEDDINGS_PROVIDER: str = "local"
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    
    # Database Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    MONGODB_URI: str = "mongodb://localhost:27017"
    
    class Config:
        env_file = ".env"

settings = Settings()
