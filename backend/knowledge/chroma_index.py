"""
knowledge/chroma_index.py
Adapter exposing the existing Chroma collection (vectorstore/store.py) as a VectorIndex.
Imports are lazy so the rest of the knowledge package stays stdlib-only.
NOTE: not exercised by the offline test-suite (ChromaDB cannot be installed in the build sandbox).
"""
from __future__ import annotations


class ChromaIndex:
    def __init__(self, collection=None):
        self._collection = collection

    @property
    def collection(self):
        if self._collection is None:
            from vectorstore.store import get_collection
            self._collection = get_collection()
        return self._collection

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        if ids:
            self.collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def delete(self, ids) -> None:
        if ids:
            self.collection.delete(ids=list(ids))

    def query(self, embedding, n: int) -> list[tuple[str, float]]:
        """Nearest vectors as (chunk_id, cosine similarity). The collection is created with hnsw:space=cosine."""
        count = self.collection.count()
        if count == 0:
            return []
        res = self.collection.query(query_embeddings=[embedding], n_results=min(n, count), include=["distances"])
        return [(cid, 1.0 - float(d)) for cid, d in zip(res["ids"][0], res["distances"][0])]
