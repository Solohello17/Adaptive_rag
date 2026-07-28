from typing import List, TypedDict
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import QdrantVectorStore
from langgraph.graph import START, END, StateGraph

from app.llm import get_llm, get_embeddings
from app.database import get_qdrant_client

# 1. State Definition
class GraphState(TypedDict):
    """
    Represents the state of our graph.
    
    Attributes:
        question: question asked by the user
        generation: LLM generation
        documents: list of documents retrieved from vectorstore
    """
    question: str
    generation: str
    documents: List[Document]

# 2. Node Functions
def retrieve(state: GraphState):
    """
    Retrieve documents from the vector store based on the question.
    """
    print("---RETRIEVE---")
    question = state["question"]
    
    # Initialize the retriever. Note: doing this inside the node to ensure 
    # we get the latest LLM/Embeddings if environment variables change (or could be global)
    qdrant_client = get_qdrant_client()
    embeddings = get_embeddings()
    
    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name="documents", # Searching the default documents collection
        embedding=embeddings
    )
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    documents = retriever.invoke(question)
    
    return {"documents": documents, "question": question}


def generate(state: GraphState):
    """
    Generate answer using the LLM and retrieved documents.
    """
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    
    llm = get_llm()
    
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
    
    return {"generation": response.content, "question": question}

# 3. Graph Construction
def build_graph():
    """
    Build and compile the LangGraph.
    """
    # Initialize the StateGraph with our GraphState
    workflow = StateGraph(GraphState)
    
    # Add our nodes to the graph
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("generate", generate)
    
    # Define the execution flow (wiring)
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)
    
    # Compile the graph into an executable application
    app = workflow.compile()
    
    return app

# A global compiled graph instance ready to be imported and used
rag_app = build_graph()
