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

    # v2.0 decision layer. DECISION_PROVIDER picks who makes the route / grade /
    # verify decisions: "llm" (the v1 path, unchanged) or "jev" (TypeSafe Jev via
    # the Vercel AI Gateway, falling back to the LLM per decision). Generation
    # always stays on the LLM. See docs/v2-jev/02-design.md.
    APP_VERSION: str = "2.0.0"
    DECISION_PROVIDER: str = "llm"
    AI_GATEWAY_API_KEY: Optional[str] = None
    JEV_BASE_URL: str = "https://ai-gateway.vercel.sh/typesafe"
    JEV_MODEL: str = "typesafe-ai/jev"
    JEV_TIMEOUT_SECONDS: float = 10
    # Chunks graded at once. Kept low to stay inside free-tier rate limits.
    JEV_MAX_CONCURRENCY: int = 3
    # Thresholds are starting guesses, not measured. Tune from the Phase 5 eval.
    JEV_ROUTE_MIN_CONFIDENCE: float = 0.6
    JEV_GRADE_THRESHOLD: float = 0.5
    JEV_VERIFY_THRESHOLD: float = 0.5
    # Character guard for Jev's reported ~32k-token state limit (roughly 4
    # characters per token in English). Longer states skip Jev and use the LLM.
    JEV_MAX_STATE_CHARS: int = 60000
    JEV_FALLBACK_TO_LLM: bool = True
    JEV_LOG_DECISIONS: bool = True

settings = Settings()
