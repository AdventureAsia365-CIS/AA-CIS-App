"""
shared/rag/repository.py
GoldenTourRepository — ChromaDB-backed few-shot retrieval.
Follows BaseRepository interface pattern (adapted for ChromaDB, not SQL).
"""
import json
import structlog
from typing import Optional

from .client import get_collection, COLLECTION_NAME

logger = structlog.get_logger()


class GoldenTourRepository:
    """
    Repository for golden tour examples used as few-shot context
    in Content Generation (LangGraph).

    Storage: ChromaDB collection 'golden_tours'
    Embedding: ChromaDB default (all-MiniLM-L6-v2 via sentence-transformers)
    Namespace: tenant_id prefix on document IDs for isolation
    """

    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection = get_collection(collection_name)

    def insert(self, data: dict) -> str:
        """
        Insert a golden tour example.

        Args:
            data: {
                id: str,                    # unique ID e.g. "golden_001"
                tenant_id: str,             # "aa-internal" for Phase 1
                country: str,
                src_name: str,              # original name (before rewrite)
                aa_name: str,               # rewritten name
                aa_summary: str,            # rewritten summary
                aa_highlights: list[str],
                quality_score: float,
            }
        Returns:
            doc_id: str
        """
        doc_id = f"{data['tenant_id']}_{data['id']}"

        # Document text for embedding = src_name + country (query context)
        document = f"{data.get('src_name', '')} {data.get('country', '')}"

        # Store full before/after as metadata for few-shot prompt injection
        metadata = {
            "tenant_id":      data.get("tenant_id", "aa-internal"),
            "country":        data.get("country", ""),
            "src_name":       data.get("src_name", "")[:500],
            "aa_name":        data.get("aa_name", "")[:500],
            "aa_summary":     data.get("aa_summary", "")[:1000],
            "aa_highlights":  json.dumps(data.get("aa_highlights", [])),
            "quality_score":  str(data.get("quality_score", 0.0)),
        }

        self.collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )

        logger.info("golden_tour_inserted", doc_id=doc_id, country=data.get("country"))
        return doc_id

    def get_by_id(self, id: str) -> Optional[dict]:
        """Get a golden tour by document ID."""
        result = self.collection.get(ids=[id], include=["metadatas", "documents"])
        if not result["ids"]:
            return None
        return {
            "id":       result["ids"][0],
            "document": result["documents"][0],
            **result["metadatas"][0],
        }

    def list(self, tenant_id: str = "aa-internal", limit: int = 20) -> list:
        """List all golden tours for a tenant."""
        result = self.collection.get(
            where={"tenant_id": tenant_id},
            limit=limit,
            include=["metadatas", "documents"],
        )
        return [
            {"id": id_, "document": doc, **meta}
            for id_, doc, meta in zip(
                result["ids"], result["documents"], result["metadatas"]
            )
        ]

    def query_similar(
        self,
        tour_name: str,
        country: str,
        tenant_id: str = "aa-internal",
        n_results: int = 3,
    ) -> list:
        """
        Find N most similar golden tours for few-shot prompting.

        Args:
            tour_name: Source tour name (used as query text)
            country:   Destination country
            tenant_id: Tenant namespace
            n_results: Number of examples to return (default 3)

        Returns:
            List of few-shot dicts with before/after content
        """
        query_text = f"{tour_name} {country}"

        try:
            result = self.collection.query(
                query_texts=[query_text],
                n_results=min(n_results, self.collection.count()),
                where={"tenant_id": tenant_id},
                include=["metadatas", "distances"],
            )
        except Exception as e:
            logger.warning("chroma_query_failed", error=str(e))
            return []

        if not result["ids"] or not result["ids"][0]:
            return []

        few_shots = []
        for meta, dist in zip(result["metadatas"][0], result["distances"][0]):
            # Skip low-relevance results (cosine distance > 0.8)
            if dist > 0.8:
                continue

            few_shots.append({
                "src_name":      meta.get("src_name", ""),
                "aa_name":       meta.get("aa_name", ""),
                "aa_summary":    meta.get("aa_summary", ""),
                "aa_highlights": json.loads(meta.get("aa_highlights", "[]")),
                "country":       meta.get("country", ""),
                "quality_score": float(meta.get("quality_score", 0.0)),
                "similarity":    round(1 - dist, 3),
            })

        logger.info(
            "few_shots_retrieved",
            query=query_text,
            count=len(few_shots),
        )
        return few_shots

    def count(self, tenant_id: str = "aa-internal") -> int:
        """Count golden tours for a tenant."""
        result = self.collection.get(where={"tenant_id": tenant_id})
        return len(result["ids"])

    def delete(self, doc_id: str) -> None:
        """Delete a golden tour by ID."""
        self.collection.delete(ids=[doc_id])
        logger.info("golden_tour_deleted", doc_id=doc_id)
