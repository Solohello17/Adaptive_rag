import logging
import time
from typing import List, TypedDict, Dict, Any, Optional, Tuple
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langgraph.graph import START, END, StateGraph
from langchain_tavily import TavilySearch

from app.config import settings
from app.llm import get_llm, get_embeddings
from app.database import get_qdrant_client
from app.decisions.factory import get_decision_provider
from app.decisions.base import route_summary, grade_summary, verify_summary

logger = logging.getLogger(__name__)


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)

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
    context: Optional[str]
    # v2: one summary per route / grade / verify decision (who decided, result,
    # confidence, latency, fallback). Built with the same manual list pattern as steps.
    decisions: List[Dict[str, Any]]

# 2. Node Functions
def check_similarity_override(question: str) -> Tuple[Optional[str], float]:
    """
    Cheap safety net for the LLM router: embeds the question locally and does
    a one-shot top-1 similarity lookup against both Qdrant collections -- no
    LLM call, just the embedding model and a vector search. Returns the
    collection with the best score, mapped back to a route name ("documents"
    or "code"), and that score, so the caller can decide whether it's strong
    enough to override a web_search/general_knowledge routing decision that
    might just be the result of a thin or missing document description.
    """
    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(question)
    qdrant_client = get_qdrant_client()

    best_route, best_score = None, 0.0
    for collection_name, route_name in [("documents", "documents"), ("code_documents", "code")]:
        try:
            hits = qdrant_client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=1,
            ).points
        except Exception as e:
            logger.debug("Similarity probe against %s failed: %s", collection_name, e)
            continue

        if hits and hits[0].score > best_score:
            best_score = hits[0].score
            best_route = route_name

    return best_route, best_score


def route_question_node(state: GraphState):
    """
    Route the question to the appropriate datasource, then sanity-check a
    web_search/general_knowledge decision against a local similarity probe
    before trusting it -- see check_similarity_override above.
    """
    print("--- ROUTE ---")
    question = state["question"]
    provider = get_decision_provider()
    start = time.perf_counter()
    decision = provider.route(question)
    datasource = decision.route
    # The summary records the provider's own decision; an override below shows up in steps.
    decisions = [route_summary(decision, _ms_since(start))]
    steps = [{"name": "route", "detail": f"matches {datasource}"}]

    # Probe on every query (~40ms, no LLM call) so the score is always logged
    # for threshold tuning, but only act on it for web_search/general_knowledge.
    override_route, score = check_similarity_override(question)
    logger.info(
        "Similarity probe: router=%s best_match=%s score=%.3f threshold=%.2f",
        datasource, override_route, score, settings.ROUTER_OVERRIDE_THRESHOLD,
    )

    if datasource in ("web_search", "general_knowledge"):
        if override_route and score >= settings.ROUTER_OVERRIDE_THRESHOLD:
            print(f"--- ROUTE OVERRIDE: {score:.3f} similarity match in {override_route}, retrieving instead ---")
            steps.append({
                "name": "route override",
                "detail": "strong match found in knowledge base, retrieving instead"
            })
            datasource = override_route

    return {"route": datasource, "steps": steps, "retry_count": 0, "decisions": decisions}

def retrieve(state: GraphState):
    """
    Retrieve documents from the vector store, grouped by source document
    instead of a flat top-k over the whole collection. A flat top-k lets one
    document -- especially a heavily-chunked or accidentally-duplicated one --
    occupy every slot and crowd out a real match that only has a few chunks.
    Grouping guarantees up to RETRIEVAL_DOCS_PER_QUERY distinct documents each
    get considered, taking up to RETRIEVAL_CHUNKS_PER_DOC chunks from each.
    """
    print("--- RETRIEVE ---")
    question = state["question"]

    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(question)
    qdrant_client = get_qdrant_client()

    collection_name = "code_documents" if state["route"] == "code" else "documents"

    groups = qdrant_client.query_points_groups(
        collection_name=collection_name,
        query=query_vector,
        group_by="metadata.source",
        limit=settings.RETRIEVAL_DOCS_PER_QUERY,
        group_size=settings.RETRIEVAL_CHUNKS_PER_DOC,
    ).groups

    documents = [
        Document(
            page_content=hit.payload.get("page_content", ""),
            metadata=hit.payload.get("metadata", {}),
        )
        for group in groups
        for hit in group.hits
    ]

    steps = state.get("steps", []) + [{
        "name": "retrieve",
        "detail": f"{len(documents)} chunks from {len(groups)} documents in the knowledge base"
    }]
    return {"documents": documents, "question": question, "steps": steps, "documents_found": len(documents)}

def grade_documents(state: GraphState):
    """
    Determines whether the retrieved documents are relevant to the question.
    """
    print("--- GRADE DOCUMENTS ---")
    question = state["question"]
    documents = state["documents"]

    provider = get_decision_provider()
    start = time.perf_counter()
    grades = provider.grade(question, [doc.page_content for doc in documents])
    decisions = state.get("decisions", []) + [grade_summary(grades, provider.name, _ms_since(start))]

    filtered_docs = []
    for doc, grade in zip(documents, grades):
        if grade.relevant:
            print("--- GRADE: DOCUMENT RELEVANT ---")
            filtered_docs.append(doc)
        else:
            print("--- GRADE: DOCUMENT IRRELEVANT ---")

    steps = state.get("steps", []) + [{"name": "grade documents", "detail": f"{len(filtered_docs)} relevant, {len(documents) - len(filtered_docs)} dropped"}]
    return {"documents": filtered_docs, "question": question, "steps": steps, "documents_kept": len(filtered_docs), "decisions": decisions}

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
    context = "\n\n".join(doc.page_content for doc in documents)

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

        # Chain the prompt and LLM together
        chain = prompt | llm
        
        # Invoke the chain
        response = chain.invoke({"question": question, "context": context})
        
    steps = state.get("steps", []) + [{"name": "generate", "detail": f"answered from {len(documents)} chunks"}]

    # Normalize generation content (some providers like Anthropic return a list of blocks)
    generation_content = response.content
    if isinstance(generation_content, list):
        generation_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in generation_content
        )

    # retry_count is intentionally NOT touched here. This node runs on the first
    # pass too, and retry_count counts corrective cycles (a regenerate or a
    # re-search, both decided in check_generation below) -- not every call to
    # generate(). Bumping it here made every clean single-pass query report
    # "1 retry" even when no corrective cycle ever happened.
    #
    # The exact context string used here is stored so check_generation grades
    # the answer against precisely what it was generated from, whatever the
    # source (retrieved chunks, web results, or both).
    return {"generation": generation_content, "question": question, "steps": steps, "context": context}

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
    context = state.get("context") or ""
    generation = state["generation"]
    retry_count = state.get("retry_count", 0)
    steps = state.get("steps", [])

    # GUARD: Prevent infinite loops. If we've hit the retry limit, skip grading
    # entirely (no more LLM calls) and force an end.
    if retry_count >= 2:
        print("--- RETRY LIMIT REACHED, ENDING ---")
        steps = steps + [{"name": "retry limit", "detail": "stopped after 2 retries"}]
        return {"steps": steps, "route_decision": "end"}

    # Both checks come from one provider call. The provider only runs the
    # grounded check when there is context, and (for the LLM) skips the answer
    # check once the answer is ungrounded -- the same calls v1 made inline here.
    grounded = None
    logger.debug("Grounding check context: %d chars", len(context))
    provider = get_decision_provider()
    start = time.perf_counter()
    verdict = provider.verify(question, context, generation)
    decisions = state.get("decisions", []) + [verify_summary(verdict, _ms_since(start))]

    if context:
        grounded = verdict.grounded

        if not grounded:
            print("--- DECISION: not grounded, RETRY GENERATE ---")
            steps = steps + [{"name": "grounding check", "detail": "failed, regenerating"}]
            # A corrective cycle -- counted here, not in generate().
            return {"grounded": grounded, "steps": steps, "route_decision": "generate", "retry_count": retry_count + 1, "decisions": decisions}

        steps = steps + [{"name": "grounding check", "detail": "passed"}]

    print("--- CHECK ANSWER ---")
    if verdict.answers_question is False:
        print("--- DECISION: grounded but unhelpful, WEB SEARCH ---")
        steps = steps + [{"name": "answer check", "detail": "did not address the question"}]
        # Also a corrective cycle. Without counting it, the answer-check ->
        # web_search -> generate loop has no hard cap (CLAUDE.md rule #4).
        return {"grounded": grounded, "steps": steps, "route_decision": "web_search", "retry_count": retry_count + 1, "decisions": decisions}

    print("--- DECISION: answer is good, END ---")
    steps = steps + [{"name": "answer check", "detail": "passed"}]
    return {"grounded": grounded, "steps": steps, "route_decision": "end", "decisions": decisions}


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
