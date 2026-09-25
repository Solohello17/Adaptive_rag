from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env into os.environ once, before Settings() is built. The search
# walks upward from this file rather than the current working directory, so
# the same .env is found no matter where the server or a script is started
# from. (dotenv's own find_dotenv() falls back to the working directory under
# `python -c` and REPLs, so it isn't used here.) Loading into os.environ, not
# just into Settings, matters because provider SDKs like ChatGroq read their
# API keys from there directly. Existing environment variables take
# precedence over .env values.
for _directory in Path(__file__).resolve().parents:
    if (_directory / ".env").is_file():
        load_dotenv(_directory / ".env")
        break

class Settings(BaseSettings):
    # Provider Selection
    LLM_PROVIDER: str = "gemini"
    LLM_PROVIDER_FAST: str = "groq"
    EMBEDDINGS_PROVIDER: str = "local"
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    # An alias Google keeps pointed at the current Flash model, so it doesn't
    # get retired the way pinned IDs like gemini-2.5-pro did. Pro models have
    # no free-tier quota.
    GEMINI_MODEL: str = "gemini-flash-latest"
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

settings = Settings()
