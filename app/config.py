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
    OMNIROUTE_BASE_URL: str = "http://localhost:20128/v1"
    OMNIROUTE_API_KEY: Optional[str] = None
    OMNIROUTE_MODEL: str = "auto/coding:free"

    # Database Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    MONGODB_URI: str = "mongodb://localhost:27017"

    # If the router picks web_search/general_knowledge but a local (no-LLM)
    # similarity probe against Qdrant scores at or above this, override it and
    # retrieve instead. all-MiniLM-L6-v2 scores run low and the answerable /
    # unanswerable ranges overlap (an unrelated weather query hit 0.319), so
    # this is set high to avoid false overrides at the cost of missing weaker
    # true matches. Re-tune from the INFO-level "Similarity probe" log line,
    # and again if EMBEDDINGS_PROVIDER changes.
    ROUTER_OVERRIDE_THRESHOLD: float = 0.6

    # Log level for this app's own loggers (app.*). DEBUG adds the grounding
    # check's context length.
    LOG_LEVEL: str = "INFO"

    # Retrieval diversity: instead of a flat top-k over the whole collection
    # (where one heavily-chunked or duplicated document can occupy every slot),
    # group results by source document. RETRIEVAL_DOCS_PER_QUERY is how many
    # distinct source documents to consider; RETRIEVAL_CHUNKS_PER_DOC is how
    # many chunks to take from each of those documents.
    RETRIEVAL_DOCS_PER_QUERY: int = 4
    RETRIEVAL_CHUNKS_PER_DOC: int = 3

    class Config:
        env_file = ".env"

settings = Settings()
