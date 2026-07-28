import uuid
from typing import List, Dict, Any
from datetime import datetime, timezone
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

# Qdrant configuration
qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

# MongoDB configuration
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
mongo_db = mongo_client["adaptive_rag"]
mongo_metadata_collection = mongo_db["document_metadata"]

def init_qdrant_collections(vector_size: int = 384):
    """
    Initialize Qdrant collections on startup if they don't exist.
    vector_size depends on the embedding model (e.g., all-MiniLM-L6-v2 uses 384).
    You might want to fetch this dynamically based on the chosen EMBEDDINGS_PROVIDER in a production app.
    """
    collections_to_create = ["documents", "code_documents"]
    
    existing_collections = [c.name for c in qdrant_client.get_collections().collections]
    
    for collection_name in collections_to_create:
        if collection_name not in existing_collections:
            qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=vector_size,
                    distance=qmodels.Distance.COSINE
                )
            )

def get_qdrant_client() -> QdrantClient:
    return qdrant_client

async def save_document_metadata(
    filename: str, 
    description: str, 
    collection_name: str, 
    chunk_count: int
) -> str:
    """
    Save document metadata to MongoDB and return the document ID.
    """
    doc_id = str(uuid.uuid4())
    metadata = {
        "_id": doc_id,
        "filename": filename,
        "description": description,
        "upload_timestamp": datetime.now(timezone.utc),
        "collection": collection_name,
        "chunk_count": chunk_count
    }
    
    await mongo_metadata_collection.insert_one(metadata)
    return doc_id
