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

def new_document_id() -> str:
    return str(uuid.uuid4())

async def save_document_metadata(
    doc_id: str,
    filename: str,
    description: str,
    collection_name: str,
    chunk_count: int
) -> str:
    """
    Save document metadata to MongoDB under doc_id (the same id every Qdrant
    chunk of this document carries as metadata.doc_id) and return it.
    """
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


async def list_documents() -> List[Dict[str, Any]]:
    """
    Returns id + filename + chunk_count for every ingested document, for the
    frontend to repopulate the knowledge-base list on page load.
    """
    cursor = mongo_metadata_collection.find({}, {"filename": 1, "chunk_count": 1}).sort("upload_timestamp", 1)
    docs = await cursor.to_list(length=None)
    return [{"id": d["_id"], "filename": d["filename"], "chunk_count": d.get("chunk_count")} for d in docs]


async def delete_document(doc_id: str) -> bool:
    """
    Removes a document's chunks from its Qdrant collection and its metadata
    record from MongoDB. Qdrant goes first: if it fails, the Mongo record is
    left in place so the document stays visible and the delete can be retried,
    rather than leaving orphaned vectors that no longer appear in the UI.
    Returns False if no document has this id.
    """
    record = await mongo_metadata_collection.find_one({"_id": doc_id})
    if record is None:
        return False

    qdrant_client.delete(
        collection_name=record.get("collection", "documents"),
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="metadata.doc_id", match=qmodels.MatchValue(value=doc_id))]
            )
        ),
    )
    await mongo_metadata_collection.delete_one({"_id": doc_id})
    return True
