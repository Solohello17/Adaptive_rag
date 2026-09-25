import os
from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv

# Load environment variables (useful for standalone execution)
load_dotenv()

# We only import the factory function, keeping the provider abstracted
from app.llm import get_llm

# 1. Define the Pydantic model for structured output
class RouteQuery(BaseModel):
    """Route a user query to the most relevant datasource."""
    
    datasource: Literal["documents", "code", "web_search", "general_knowledge"] = Field(
        ...,
        description=(
            "Given a user question choose to route it to one of the following datasources:\n"
            "- 'documents': The answer is likely found in our indexed knowledge-base documents (e.g. PDFs, TXTs, manuals).\n"
            "- 'code': The question is specifically about code, software architecture, functions, or indexed code files.\n"
            "- 'web_search': The question requires current, live, or external information that we don't have stored.\n"
            "- 'general_knowledge': The model can answer this directly without needing to look up any external information (e.g. greetings, simple facts)."
        ),
    )

# 2. Build the router chain
def get_question_router():
    """
    Builds and returns the question router chain.
    Pipes a system prompt into the LLM with structured output enforced.
    """
    # Get the provider-agnostic LLM
    llm = get_llm(model_type="fast")

    # Enforce structured output using the Pydantic model
    structured_llm_router = llm.with_structured_output(RouteQuery)

    # Create the routing system prompt
    system_prompt = """You are an expert at routing a user question to the appropriate datasource.

    You MUST route the question to exactly one of these four categories: 'documents', 'code', 'web_search', or 'general_knowledge'.

    - Route to 'documents' if the question is about the system manual, student login, grading, internal guidelines, or knowledge base.
    - Route to 'code' if the question is about the codebase, Python, FastAPI, LangGraph, or databases.
    - Route to 'general_knowledge' if the question is a greeting or general chit-chat.
    - Route to 'web_search' for recent events or things outside the specific domains above.

    You must respond in JSON format with exactly one key "datasource".
    Example: {{"datasource": "web_search"}}
    """

    prompt = PromptTemplate.from_template(
        system_prompt + "\n\nUser Question: {question}"
    )

    # Chain the prompt and the structured LLM
    question_router = prompt | structured_llm_router
    return question_router

# 3. Convenience function to invoke the router
def route_question(question: str, router=None) -> str:
    """
    Invokes the router on a given question and returns the chosen datasource string.
    """
    if router is None:
        router = get_question_router()
        
    result = router.invoke({"question": question})
    return result.datasource

# 4. Standalone execution block for testing
if __name__ == "__main__":
    print("Initializing Adaptive Router...")
    router_chain = get_question_router()
    
    # 5 sample questions covering all routes + 1 ambiguous
    sample_questions = [
        "What are the main findings in the uploaded Q3 financial report PDF?", # Should be documents
        "How does the init_qdrant_collections function work in our codebase?", # Should be code
        "What is the weather like in Tokyo right now?",                        # Should be web_search
        "Hello there! How are you doing today?",                               # Should be general_knowledge
        "What is the best way to optimize a vector database?"                  # Ambiguous (could be code or general_knowledge)
    ]
    
    print("\n--- Router Tests ---")
    for q in sample_questions:
        chosen_route = route_question(q, router=router_chain)
        print(f"{chosen_route} <- {q}")
