import os
import io
import logging
import uuid
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore

from app.database import (
    init_qdrant_collections,
    new_document_id,
    save_document_metadata,
    get_qdrant_client,
    list_documents,
    delete_document,
)
from app.config import settings
from app.llm import get_embeddings
from app.graph import rag_app
from app.decisions.factory import get_decision_provider
from app.decisions.decision_log import request_id_var

# Uvicorn only configures handlers for its own loggers, so without this our
# app.* INFO/DEBUG lines are silently dropped. Root stays at WARNING, which
# keeps httpx/pymongo/huggingface chatter out of the terminal.
logging.basicConfig(format="%(levelname)s:     %(name)s - %(message)s")
logging.getLogger("app").setLevel(settings.LOG_LEVEL.upper())

# Triggering uvicorn hot-reload to pick up .env changes


app = FastAPI(title="Adaptive RAG - Layer 1")

@app.on_event("startup")
async def startup_event():
    # Initialize Qdrant collections on startup
    init_qdrant_collections()
    # Load the embedding model now so the first query doesn't pay the ~6-13s load.
    get_embeddings()
    print("Startup: Qdrant collections checked/initialized.")
    # Build the decision provider now so a bad DECISION_PROVIDER setup (e.g. jev
    # without AI_GATEWAY_API_KEY) stops the server at boot, not on the first query.
    print(f"Startup: decision provider = {get_decision_provider().name}")

@app.post("/rag/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    x_description: str = Header(..., alias="X-Description")
):
    """
    Ingest a document (PDF/TXT), chunk it, embed it, save to Qdrant, and write metadata to Mongo.
    """
    if file.content_type not in ["application/pdf", "text/plain"]:
        raise HTTPException(status_code=400, detail="Only PDF or TXT files are supported.")
        
    content = await file.read()
    text = ""
    
    if file.content_type == "application/pdf":
        try:
            pdf = PdfReader(io.BytesIO(content))
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading PDF: {str(e)}")
    else:
        text = content.decode("utf-8")
        
    if not text.strip():
        raise HTTPException(status_code=400, detail="Document is empty or could not be read.")
        
    # Chunking
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    texts = text_splitter.split_text(text)

    # Every chunk carries the document's id so it can be deleted precisely later,
    # even if another document with the same filename is uploaded.
    doc_id = new_document_id()
    documents = [
        Document(page_content=t, metadata={"source": file.filename, "doc_id": doc_id})
        for t in texts
    ]

    # Embedding and Upserting to Qdrant
    try:
        embeddings = get_embeddings()
        qdrant_client = get_qdrant_client()
        
        vector_store = QdrantVectorStore(
            client=qdrant_client,
            collection_name="documents",
            embedding=embeddings
        )
        
        vector_store.add_documents(documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error upserting to Qdrant: {str(e)}")
        
    # Save metadata to MongoDB
    try:
        await save_document_metadata(
            doc_id=doc_id,
            filename=file.filename,
            description=x_description,
            collection_name="documents",
            chunk_count=len(documents)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving to MongoDB: {str(e)}")

    return {
        "message": "Document ingested successfully",
        "doc_id": doc_id,
        "filename": file.filename,
        "chunks": len(documents)
    }


@app.get("/rag/documents")
async def get_documents():
    """
    Lists all ingested documents (id, filename, chunk count) so the frontend can
    repopulate the knowledge-base list on page load, not just within the
    current browser session.
    """
    return await list_documents()


@app.delete("/rag/documents/{doc_id}")
async def remove_document(doc_id: str):
    """
    Deletes a document's vectors from Qdrant and its metadata from MongoDB.
    """
    try:
        found = await delete_document(doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting document: {str(e)}")
    if not found:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"message": "Document deleted", "doc_id": doc_id}


from typing import List, Optional

class QueryRequest(BaseModel):
    question: str

class Step(BaseModel):
    name: str
    detail: str

class DecisionSummary(BaseModel):
    decision: str                           # route | grade | verify
    provider: str                           # jev | llm | mixed (grade only: some chunks fell back)
    result: str
    confidence: Optional[float] = None
    latency_ms: float
    fallback_reason: Optional[str] = None
    fallback_count: Optional[int] = None    # grade only

class QueryResponse(BaseModel):
    answer: str
    route: str
    documents_found: Optional[int] = None
    documents_kept: Optional[int] = None
    grounded: Optional[bool] = None
    retry_count: int
    failed: bool
    steps: List[Step]
    # v2, additive: who made each route / grade / verify decision. Every field above is unchanged.
    decisions: Optional[List[DecisionSummary]] = None

@app.post("/query", response_model=QueryResponse)
async def query_graph(request: QueryRequest):
    """
    Execute the LangGraph workflow to retrieve context and generate an answer.
    """
    # Ties this query's decision logs together in MongoDB.
    request_token = request_id_var.set(str(uuid.uuid4()))
    try:
        initial_state = {"question": request.question}
        result = rag_app.invoke(initial_state)
        
        retry_count = result.get("retry_count", 0)
        route = result.get("route", "")
        documents = result.get("documents", [])
        
        # Determine if the query failed
        failed = False
        if retry_count >= 2:
            failed = True
        elif route != "general_knowledge" and not documents:
            failed = True
            
        return QueryResponse(
            answer=result.get("generation", ""),
            route=route,
            documents_found=result.get("documents_found"),
            documents_kept=result.get("documents_kept"),
            grounded=result.get("grounded"),
            retry_count=retry_count,
            failed=failed,
            steps=[Step(**s) for s in result.get("steps", [])],
            decisions=[DecisionSummary(**d) for d in result.get("decisions", [])],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing graph: {str(e)}")
    finally:
        request_id_var.reset(request_token)

# Mount static files (must be after API routes)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
