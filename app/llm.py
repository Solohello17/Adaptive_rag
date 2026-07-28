from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from app.config import settings

def get_llm() -> BaseChatModel:
    """
    Factory function to get the configured LLM provider.
    Provider classes are only imported here to keep the rest of the application agnostic.
    """
    provider = settings.LLM_PROVIDER.lower()
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Ensure you have GOOGLE_API_KEY in your environment
        return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0)
        
    elif provider == "claude" or provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        # Ensure you have ANTHROPIC_API_KEY in your environment
        return ChatAnthropic(model="claude-3-opus-20240229", temperature=0)
        
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        # Ensure you have OPENAI_API_KEY in your environment
        return ChatOpenAI(model="gpt-4o", temperature=0)
        
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
