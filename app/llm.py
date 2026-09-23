from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from app.config import settings

def get_llm(model_type: str = "smart") -> BaseChatModel:
    """
    Factory function to get the configured LLM provider.
    Provider classes are only imported here to keep the rest of the application agnostic.
    """
    if model_type == "fast":
        provider = getattr(settings, "LLM_PROVIDER_FAST", settings.LLM_PROVIDER).lower()
    else:
        provider = settings.LLM_PROVIDER.lower()
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Ensure you have GOOGLE_API_KEY in your environment
        return ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0)
        
    elif provider == "claude" or provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        # Ensure you have ANTHROPIC_API_KEY in your environment
        return ChatAnthropic(model="claude-3-opus-20240229", temperature=0)
        
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        # Ensure you have OPENAI_API_KEY in your environment
        return ChatOpenAI(model="gpt-4o", temperature=0)
        
    elif provider == "groq":
        from langchain_groq import ChatGroq
        
        class SafeChatGroq(ChatGroq):
            def with_structured_output(self, schema, **kwargs):
                # Force json_mode because Groq sometimes outputs XML-like strings in tool-calling mode
                kwargs["method"] = "json_mode"
                return super().with_structured_output(schema, **kwargs)
                
        return SafeChatGroq(model=settings.GROQ_MODEL, temperature=0)
        
    elif provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        
        # ChatNVIDIA supports with_structured_output via standard function calling.
        # However, because we explicitly inject JSON schemas into the prompt in router.py 
        # and grader.py (to satisfy Groq's json_mode), we can also force JSON mode for NVIDIA 
        # to ensure the models output exactly the keys we requested in the prompt, avoiding 
        # any schema mismatch issues.
        class SafeChatNVIDIA(ChatNVIDIA):
            def with_structured_output(self, schema, **kwargs):
                kwargs["method"] = "json_mode"
                return super().with_structured_output(schema, **kwargs)
                
        return SafeChatNVIDIA(
            model=settings.NVIDIA_MODEL, 
            temperature=0
        )
        
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI

        # OpenRouter speaks the OpenAI API format, so we reuse ChatOpenAI with a
        # custom base_url instead of adding a new SDK dependency.
        #
        # Model IDs are namespaced as "provider/model-name" (e.g. some carry a
        # ":free" suffix for free-tier variants, like "meta-llama/llama-3.1-8b-instruct:free").
        # Copy the exact ID for the model you want from https://openrouter.ai/models --
        # don't guess it, OpenRouter will 400 on an unrecognized one.
        class SafeChatOpenRouter(ChatOpenAI):
            def with_structured_output(self, schema, **kwargs):
                # ChatOpenAI defaults to method="function_calling" (tool calling), but
                # OpenRouter fronts many models and support for that varies a lot by
                # the underlying model -- most free-tier ones don't support it at all.
                # json_mode is far more broadly supported across OpenRouter's catalog,
                # and router.py / grader.py already spell out the exact JSON shape they
                # want in the prompt, so we force it here the same way we do for Groq/NVIDIA.
                kwargs["method"] = "json_mode"
                return super().with_structured_output(schema, **kwargs)

        return SafeChatOpenRouter(
            model=settings.OPENROUTER_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            default_headers={
                # Optional, but OpenRouter uses these to attribute requests to your
                # app on its dashboard/leaderboards. Harmless to leave as defaults.
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-Title": settings.OPENROUTER_APP_NAME,
            },
        )

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def get_embeddings() -> Embeddings:
    """
    Factory function to get the configured Embeddings provider.
    """
    provider = settings.EMBEDDINGS_PROVIDER.lower()
    
    if provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model="text-embedding-3-small")
        
    elif provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings
        # Uses sentence-transformers locally
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        
    else:
        raise ValueError(f"Unsupported EMBEDDINGS_PROVIDER: {provider}")
