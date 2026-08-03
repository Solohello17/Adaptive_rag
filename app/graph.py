from typing import List, TypedDict, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import QdrantVectorStore
from langgraph.graph import START, END, StateGraph
from langchain_tavily import TavilySearch

from app.llm import get_llm, get_embeddings
from app.database import get_qdrant_client
from app.router import route_question
from app.grader import grade_document, grade_hallucination, grade_answer

# 1. State Definition
class GraphState(TypedDict):
    """
    Represents the state of our graph.
    
    Attributes:
        question: question asked by the user
        generation: LLM generation
        documents: list of documents retrieved from vectorstore
        route: the routing decision for the question
    """
    question: str
    generation: str
    documents: List[Document]
    route: str
    retry_count: int
    steps: List[Dict[str, str]]
    documents_found: Optional[int]
    documents_kept: Optional[int]
    grounded: Optional[bool]
    route_decision: Optional[str]

# 2. Node Functions
def route_question_node(state: GraphState):
    """
    Route the question to the appropriate datasource.
    """
    print("--- ROUTE ---")
    question = state["question"]
    datasource = route_question(question)
    step = {"name": "route", "detail": f"matches {datasource}"}
    return {"route": datasource, "steps": [step], "retry_count": 0}

def retrieve(state: GraphState):
    """
    Retrieve documents from the vector store based on the question.
    """
    print("--- RETRIEVE ---")
    question = state["question"]
    
    # Initialize the retriever. Note: doing this inside the node to ensure
    # we get the latest LLM/Embeddings if environment variables change (or could be global)
    qdrant_client = get_qdrant_client()
    embeddings = get_embeddings()

    collection_name = "code_documents" if state["route"] == "code" else "documents"

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=collection_name,
        embedding=embeddings
    )
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    documents = retriever.invoke(question)
    
    steps = state.get("steps", []) + [{"name": "retrieve", "detail": f"{len(documents)} chunks from the knowledge base"}]
    return {"documents": documents, "question": question, "steps": steps, "documents_found": len(documents)}

def grade_documents(state: GraphState):
    """
    Determines whether the retrieved documents are relevant to the question.
    """
    print("--- GRADE DOCUMENTS ---")
    question = state["question"]
    documents = state["documents"]
    
    # Grade each document
    filtered_docs = []
    for doc in documents:
        score = grade_document(question, doc.page_content)
        if score == "yes":
            print("--- GRADE: DOCUMENT RELEVANT ---")
            filtered_docs.append(doc)
        else:
            print("--- GRADE: DOCUMENT IRRELEVANT ---")
            
    steps = state.get("steps", []) + [{"name": "grade documents", "detail": f"{len(filtered_docs)} relevant, {len(documents) - len(filtered_docs)} dropped"}]
    return {"documents": filtered_docs, "question": question, "steps": steps, "documents_kept": len(filtered_docs)}

def decide_to_generate(state: GraphState):
    """
    Determines whether to generate an answer or fallback to web search.
    """
    filtered_documents = state["documents"]
    steps = state.setdefault("steps", [])
    
    if filtered_documents:
        # We have relevant documents, so generate answer
        print("--- DECISION: documents relevant, GENERATE ---")
        steps.append({"name": "decision", "detail": "documents relevant, generating"})
        return "generate"
    else:
        # All documents were filtered out, fallback to web search
        print("--- DECISION: no relevant docs, WEB SEARCH ---")
        steps.append({"name": "decision", "detail": "no relevant docs, fallback to web search"})
        return "web_search"
def web_search(state: GraphState):
    """
    Web search based on the user question.
    """
    print("--- WEB SEARCH ---")
    question = state["question"]
    documents = state.get("documents", [])
    
    # Web search
    tool = TavilySearch(max_results=3)
    response = tool.invoke({"query": question})

    # TavilySearch returns {"results": [{"url": "...", "content": "..."}, ...], ...}
    docs = response.get("results", [])
    web_results = "\n".join([d["content"] for d in docs])
    
    web_results_doc = Document(page_content=web_results, metadata={"source": "tavily"})
    documents.append(web_results_doc)
    
    steps = state.get("steps", []) + [{"name": "web search", "detail": "3 results from Tavily"}]
    return {"documents": documents, "question": question, "steps": steps}


def generate(state: GraphState):
    """
    Generate answer using the LLM and retrieved documents (if any).
    """
    print("--- GENERATE ---")
    question = state["question"]
    documents = state.get("documents", [])
    
    llm = get_llm()
    
    if not documents:
        # Fallback to direct answering if no context was retrieved (e.g. general_knowledge)
        template = """You are a helpful assistant. Please answer the user's question directly.
        
        Question: {question}
        
        Answer:"""
        prompt = PromptTemplate.from_template(template)
        chain = prompt | llm
        response = chain.invoke({"question": question})
    else:
        # A simple RAG prompt
        template = """You are an assistant for question-answering tasks. 
        Use the following pieces of retrieved context to answer the question. 
        If you don't know the answer, just say that you don't know. 
        Use three sentences maximum and keep the answer concise.
        
        Question: {question} 
        
        Context: {context} 
        
        Answer:"""
        
        prompt = PromptTemplate.from_template(template)
        
        # Format the documents into a single string
        context = "\n\n".join(doc.page_content for doc in documents)
        
        # Chain the prompt and LLM together
        chain = prompt | llm
        
        # Invoke the chain
        response = chain.invoke({"question": question, "context": context})
        
    retry_count = state.get("retry_count", 0)
    steps = state.get("steps", []) + [{"name": "generate", "detail": f"answered from {len(documents)} chunks"}]
    
    # Normalize generation content (some providers like Anthropic return a list of blocks)
    generation_content = response.content
    if isinstance(generation_content, list):
        generation_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) 
            for block in generation_content
        )
        
    return {"generation": generation_content, "question": question, "retry_count": retry_count + 1, "steps": steps}

def check_generation(state: GraphState):
    """
    Node: grades the generation for hallucination and answer quality, writing the
    results (and the resulting routing decision) into state.

    This used to live inside the conditional-edge function itself, which only ever
    hands its return value to LangGraph for picking the next node — anything written
    onto the state object there isn't part of the documented state-update contract
    (only node return values are merged via reducers). Doing the grading in a real
    node keeps `grounded` and the routing decision as proper, guaranteed state updates.
    """
    print("--- CHECK HALLUCINATIONS ---")
    question = state["question"]
    documents = state.get("documents", [])
    generation = state["generation"]
    retry_count = state.get("retry_count", 0)
    steps = state.get("steps", [])

    # GUARD: Prevent infinite loops. If we've hit the retry limit, skip grading
    # entirely (no more LLM calls) and force an end.
    if retry_count >= 2:
        print("--- RETRY LIMIT REACHED, ENDING ---")
        steps = steps + [{"name": "retry limit", "detail": "stopped after 2 retries"}]
        return {"steps": steps, "route_decision": "end"}

    # Only grade hallucinations if we actually have documents.
    grounded = None
    if documents:
        context = "\n\n".join(doc.page_content for doc in documents)
        score = grade_hallucination(context, generation)
        grounded = score == "yes"

        if not grounded:
            print("--- DECISION: not grounded, RETRY GENERATE ---")
            steps = steps + [{"name": "grounding check", "detail": "failed, regenerating"}]
            return {"grounded": grounded, "steps": steps, "route_decision": "generate"}

        steps = steps + [{"name": "grounding check", "detail": "passed"}]

    print("--- CHECK ANSWER ---")
    score = grade_answer(question, generation)
    if score == "no":
        print("--- DECISION: grounded but unhelpful, WEB SEARCH ---")
        steps = steps + [{"name": "answer check", "detail": "did not address the question"}]
        return {"grounded": grounded, "steps": steps, "route_decision": "web_search"}

    print("--- DECISION: answer is good, END ---")
    steps = steps + [{"name": "answer check", "detail": "passed"}]
    return {"grounded": grounded, "steps": steps, "route_decision": "end"}


def route_after_check(state: GraphState) -> str:
    """
    Pure router: just reads the decision `check_generation` already wrote into state.
    Does no grading and mutates nothing — safe to use as a conditional-edge function.
    """
    return state["route_decision"]

# 3. Graph Construction
def build_graph():
    """
    Build and compile the LangGraph.
    """
    # Initialize the StateGraph with our GraphState
    workflow = StateGraph(GraphState)
    
    # Add our nodes to the graph
    workflow.add_node("route_question", route_question_node)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("grade_documents", grade_documents)
    workflow.add_node("web_search", web_search)
    workflow.add_node("generate", generate)
    workflow.add_node("check_generation", check_generation)
    
    # Define the execution flow (wiring)
    workflow.add_edge(START, "route_question")
    
    workflow.add_conditional_edges(
        "route_question",
        lambda x: x["route"],
        {
            "documents": "retrieve",
            "code": "retrieve",
            "general_knowledge": "generate",
            "web_search": "web_search",
        }
    )
    
    workflow.add_edge("retrieve", "grade_documents")
    
    workflow.add_conditional_edges(
        "grade_documents",
        decide_to_generate,
        {
            "generate": "generate",
            "web_search": "web_search",
        }
    )
    workflow.add_edge("web_search", "generate")
    
    workflow.add_edge("generate", "check_generation")

    workflow.add_conditional_edges(
        "check_generation",
        route_after_check,
        {
            "generate": "generate",
            "web_search": "web_search",
            "end": END
        }
    )
    
    # Compile the graph into an executable application
    app = workflow.compile()
    
    return app

# A global compiled graph instance ready to be imported and used
rag_app = build_graph()
