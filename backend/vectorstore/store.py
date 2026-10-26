"""
vectorstore/store.py
ChromaDB persistent vector store — loaded once at startup, reused across requests.
v2: added source_type, page_number, filename to metadata; added source_type where-filter in query_chunks().
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import CHROMA_PATH, CHROMA_COLLECTION
import numpy as np

_client: chromadb.ClientAPI = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    _client = chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    _collection = _client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]):
    """
    chunks: list of chunk dicts (video or PDF).
    embeddings: parallel list of embedding vectors.
    Metadata now includes source_type, page_number, filename for filtering.
    """
    col       = get_collection()
    ids       = [str(c["chunk_id"]) for c in chunks]
    docs      = [c["text"] for c in chunks]
    metadatas = [
        {
            # video fields
            "title":    str(c.get("Title",    c.get("filename", ""))),
            "number":   str(c.get("number",   "")),
            "start":    float(c.get("Start",  0)),
            "end":      float(c.get("end",    0)),
            "chunk_id": int(c.get("chunk_id", 0)),
            # v2: source identification
            "source_type":     str(c.get("source_type",     "video")),
            "page_number":     int(c.get("page_number",     0)),
            "filename":        str(c.get("filename",        "")),
            "section_heading": str(c.get("section_heading", "")),
        }
        for c in chunks
    ]
    col.upsert(ids=ids, embeddings=embeddings, documents=docs, metadatas=metadatas)


def query_chunks(
    query_embedding: list[float],
    top_k: int = 6,
    threshold: float = 0.25,
    source_type: str = "video",   # "video" | "pdf" | "all"
):
    """
    Returns list of result dicts with score, text, metadata.
    source_type="all" skips the where filter (used for hybrid queries).
    """
    col = get_collection()
    if col.count() == 0:
        return []

    # Build where filter — skip when source_type="all"
    where = None
    if source_type not in ("all", None, ""):
        where = {"source_type": {"$eq": source_type}}

    query_kwargs = dict(
        query_embeddings=[query_embedding],
        n_results=min(top_k, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    if where:
        query_kwargs["where"] = where

    results = col.query(**query_kwargs)

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        score = round(1.0 - float(dist), 4)
        if score < threshold:
            break
        output.append({
            "text":            doc,
            "title":           meta.get("title",           ""),
            "number":          meta.get("number",          ""),
            "start":           meta.get("start",           0.0),
            "end":             meta.get("end",             0.0),
            "chunk_id":        meta.get("chunk_id",        0),
            "score":           score,
            # v2 fields
            "source_type":     meta.get("source_type",     "video"),
            "page_number":     meta.get("page_number",     0),
            "filename":        meta.get("filename",        ""),
            "section_heading": meta.get("section_heading", ""),
        })

    return output


def total_chunks() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
