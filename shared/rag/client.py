"""
shared/rag/client.py
ChromaDB client — singleton pattern, EFS-backed in prod, local in dev/test.
"""
import os
import chromadb
from chromadb.config import Settings

_client = None

CHROMA_HOST        = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT        = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_MODE        = os.getenv("CHROMA_MODE", "local")   # local | http
CHROMA_LOCAL_PATH  = os.getenv("CHROMA_LOCAL_PATH", "/mnt/efs/chromadb")
COLLECTION_NAME    = os.getenv("CHROMA_COLLECTION", "golden_tours")


def get_client() -> chromadb.ClientAPI:
    """Return singleton ChromaDB client."""
    global _client
    if _client is not None:
        return _client

    if CHROMA_MODE == "http":
        # Production: ChromaDB running as ECS service
        _client = chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            settings=Settings(anonymized_telemetry=False),
        )
    else:
        # Dev/test: local persistent client
        _client = chromadb.PersistentClient(
            path=CHROMA_LOCAL_PATH,
            settings=Settings(anonymized_telemetry=False),
        )

    return _client


def get_collection(name: str = COLLECTION_NAME):
    """Get or create collection with cosine similarity."""
    client = get_client()
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def reset_client():
    """Reset singleton — for testing only."""
    global _client
    _client = None
