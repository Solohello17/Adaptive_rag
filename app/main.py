import os
import io
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from pydantic import BaseModel
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore

from app.database import init_qdrant_collections, save_document_metadata, get_qdrant_client
from app.llm import get_embeddings
from app.graph import rag_app

app = FastAPI(title="Adaptive RAG - Layer 1")

@app.on_event("startup")
async def startup_event():
    # Initialize Qdrant collections on startup
    init_qdrant_collections()
    print("Startup: Qdrant collections checked/initialized.")

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
    
    documents = [Document(page_content=t, metadata={"source": file.filename}) for t in texts]
    
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
        doc_id = await save_document_metadata(
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

class QueryRequest(BaseModel):
    question: str

@app.post("/query")
async def query_graph(request: QueryRequest):
    """
    Execute the LangGraph workflow to retrieve context and generate an answer.
    """
    try:
        # We start the graph by providing the initial state
        initial_state = {"question": request.question}
        
        # Invoke the compiled graph
        result = rag_app.invoke(initial_state)
        
        return {
            "question": result["question"],
            "answer": result["generation"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing graph: {str(e)}")
