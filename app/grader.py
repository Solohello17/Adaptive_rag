from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from app.llm import get_llm

class GradeDocuments(BaseModel):
    """Boolean score for relevance check on retrieved documents."""
    binary_score: Literal["yes", "no"] = Field(
        description="Whether the document is relevant to the question, 'yes' or 'no'."
    )

def get_document_grader():
    """
    Returns a chain that evaluates if a document is relevant to a question.
    """
    llm = get_llm(model_type="fast")
    structured_llm_grader = llm.with_structured_output(GradeDocuments)
    
    system = """You are a grader assessing relevance of a retrieved document to a user question. 
    If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. 
    It does not need to be a stringent test. The goal is to filter out clearly irrelevant retrievals.
    
    Return 'yes' if the document is relevant, otherwise return 'no'.
    You must respond in JSON format with exactly one key "binary_score".
    Example: {{"binary_score": "yes"}}
    
    Question: {question}
    
    Document: {document}"""
    
    grade_prompt = PromptTemplate.from_template(system)
    
    return grade_prompt | structured_llm_grader

def grade_document(question: str, document: str) -> str:
    """
    Grades the relevance of a single document against a question.
    Returns 'yes' or 'no'.
    """
    grader = get_document_grader()
    result = grader.invoke({"question": question, "document": document})
    return result.binary_score

class GradeHallucinations(BaseModel):
    """Boolean score for hallucination check on generated answer."""
    binary_score: Literal["yes", "no"] = Field(
        description="Whether the answer is grounded in and supported by the provided facts, 'yes' or 'no'."
    )

class GradeAnswer(BaseModel):
    """Boolean score for checking if answer addresses question."""
    binary_score: Literal["yes", "no"] = Field(
        description="Whether the answer addresses the question, 'yes' or 'no'."
    )

def grade_hallucination(documents: str, generation: str) -> str:
    """
    Grades if the generation is grounded in the documents.
    Returns 'yes' (grounded) or 'no' (hallucinated).
    """
    llm = get_llm(model_type="fast")
    structured_llm_grader = llm.with_structured_output(GradeHallucinations)
    
    system = """You are a grader assessing whether an LLM generation is grounded in / supported by a set of retrieved facts.
    Grade 'yes' if the answer is completely grounded in and supported by the facts. 
    Grade 'no' if it contains any hallucinations or claims outside of the provided facts.
    IMPORTANT: If the generation explicitly states that the information is not present in the context or that it does not know the answer, you must grade it as 'yes' (grounded), because acknowledging a lack of information is factually accurate based on the context.
    You must respond in JSON format with exactly one key "binary_score".
    Example: {{"binary_score": "yes"}}
    
    Documents: {documents}
    
    Generation: {generation}"""
    
    grade_prompt = PromptTemplate.from_template(system)
    grader = grade_prompt | structured_llm_grader
    
    result = grader.invoke({"documents": documents, "generation": generation})
    return result.binary_score

def grade_answer(question: str, generation: str) -> str:
    """
    Grades if the generation actually addresses the user's question.
    Returns 'yes' (addresses) or 'no' (fails to address).
    """
    llm = get_llm(model_type="fast")
    structured_llm_grader = llm.with_structured_output(GradeAnswer)
    
    system = """You are a grader assessing whether an answer addresses / resolves a question.
    Grade 'yes' if the answer is a direct, helpful response to the question.
    Grade 'no' if the answer dodges the question or fails to resolve it.
    You must respond in JSON format with exactly one key "binary_score".
    Example: {{"binary_score": "yes"}}
    
    Question: {question}
    
    Generation: {generation}"""
    
    grade_prompt = PromptTemplate.from_template(system)
    grader = grade_prompt | structured_llm_grader
    
    result = grader.invoke({"question": question, "generation": generation})
    return result.binary_score

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    print("Testing Grader...")
    
    # Relevant pair
    q_relevant = "How do I optimize a vector database?"
    doc_relevant = "To optimize a vector database, ensure you are using HNSW indexing and quantization techniques to compress the vectors."
    score1 = grade_document(q_relevant, doc_relevant)
    print(f"Test 1 (Relevant): {score1}")
    
    # Irrelevant pair
    q_irrelevant = "What is the capital of France?"
    doc_irrelevant = "Apples are a great source of fiber and vitamin C. They grow on trees in temperate climates."
    score2 = grade_document(q_irrelevant, doc_irrelevant)
    print(f"Test 2 (Irrelevant): {score2}")
    
    print("\nTesting Hallucination Grader...")
    docs_text = "SpaceX's Falcon 9 rocket uses RP-1 and liquid oxygen as propellants."
    gen_grounded = "The Falcon 9 uses liquid oxygen and RP-1."
    gen_hallucinated = "The Falcon 9 uses liquid hydrogen and is built in Texas."
    
    print(f"Test 3 (Grounded): {grade_hallucination(docs_text, gen_grounded)}")
    print(f"Test 4 (Hallucinated): {grade_hallucination(docs_text, gen_hallucinated)}")
    
    print("\nTesting Answer Grader...")
    question = "How tall is the Eiffel Tower?"
    gen_helpful = "The Eiffel Tower is 330 meters tall."
    gen_unhelpful = "The Eiffel Tower is located in Paris, France."
    
    print(f"Test 5 (Helpful): {grade_answer(question, gen_helpful)}")
    print(f"Test 6 (Unhelpful): {grade_answer(question, gen_unhelpful)}")
