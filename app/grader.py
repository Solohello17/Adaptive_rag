from typing import List, Literal
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

class GradeDocumentsBatch(BaseModel):
    """Relevance verdicts for a numbered list of retrieved documents, in order."""
    verdicts: List[Literal["yes", "no"]] = Field(
        description="One 'yes' or 'no' per document, in the same order as the numbered documents."
    )

def grade_documents_batch(question: str, documents: List[str]) -> List[str]:
    """
    Grades every retrieved chunk in a single LLM call instead of one call per
    chunk. Returns one 'yes'/'no' per document, in input order.

    The model is asked for exactly len(documents) verdicts, but nothing forces
    it to comply. If the count comes back wrong we can't tell which verdict
    belongs to which chunk, so we fall back to grading each one separately.
    """
    if not documents:
        return []

    llm = get_llm(model_type="fast")
    structured_llm_grader = llm.with_structured_output(GradeDocumentsBatch)

    system = """You are a grader assessing the relevance of retrieved documents to a user question.
    If a document contains keyword(s) or semantic meaning related to the user question, grade it as relevant.
    It does not need to be a stringent test. The goal is to filter out clearly irrelevant retrievals.
    Grade each document independently.

    There are {count} documents below, numbered [0] to [{last}].
    You must respond in JSON format with exactly one key "verdicts": a list of exactly {count} strings,
    each 'yes' or 'no', where the i-th entry is the grade for document [i].
    Example for 3 documents: {{"verdicts": ["yes", "no", "yes"]}}

    Question: {question}

    Documents:
    {documents}"""

    numbered = "\n\n".join(f"[{i}] {doc}" for i, doc in enumerate(documents))
    grader = PromptTemplate.from_template(system) | structured_llm_grader
    result = grader.invoke({
        "count": len(documents),
        "last": len(documents) - 1,
        "question": question,
        "documents": numbered,
    })

    if len(result.verdicts) != len(documents):
        print(f"--- GRADE: batch returned {len(result.verdicts)} verdicts for {len(documents)} documents, falling back to per-document grading ---")
        return [grade_document(question, doc) for doc in documents]

    return result.verdicts

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

    print("\nTesting Batch Grader...")
    batch_docs = [
        doc_relevant,
        doc_irrelevant,
        "Product quantization splits vectors into sub-vectors and compresses each one, cutting a vector index's memory use.",
    ]
    print(f"Test 2b (Batch, expect ['yes', 'no', 'yes']): {grade_documents_batch(q_relevant, batch_docs)}")

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
