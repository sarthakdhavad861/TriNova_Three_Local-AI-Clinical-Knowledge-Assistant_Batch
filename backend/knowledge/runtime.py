"""
knowledge/runtime.py
Process-wide singletons wiring the knowledge base to the real components
(SQLite store, Ollama embeddings, Chroma index). Kept separate so tests can build their own.
"""
from __future__ import annotations

from functools import lru_cache

from config.settings import (
    CHUNK_MAX_WORDS, EMBED_BATCH, EMBED_MODEL, ENCOUNTER_DB_PATH, ENCOUNTER_TTL_HOURS, KNOWLEDGE_DB_PATH, MAX_DOC_BYTES,
    MIN_LEXICAL_COVERAGE, RETRIEVE_OVERFETCH, SIM_THRESHOLD, TOP_K,
)
from knowledge.ingest import IngestionService
from knowledge.store import KnowledgeStore
from encounters.store import EncounterStore


@lru_cache(maxsize=1)
def get_store() -> KnowledgeStore:
    return KnowledgeStore(KNOWLEDGE_DB_PATH)


@lru_cache(maxsize=1)
def get_service() -> IngestionService:
    from knowledge.chroma_index import ChromaIndex
    from services.embedding import embed_texts_sync      # Ollama bge-m3 (sync; runs in worker threads)
    return IngestionService(
        get_store(), ChromaIndex(), embed_texts_sync, embed_model=EMBED_MODEL,
        max_bytes=MAX_DOC_BYTES, max_words=CHUNK_MAX_WORDS, embed_batch=EMBED_BATCH)


@lru_cache(maxsize=1)
def get_retriever():
    from knowledge.chroma_index import ChromaIndex
    from knowledge.retrieval import Retriever
    from services.embedding import embed_texts_sync
    return Retriever(
        get_store(), ChromaIndex().query, lambda q: embed_texts_sync([q])[0], top_k=TOP_K,
        overfetch=RETRIEVE_OVERFETCH, min_dense=SIM_THRESHOLD, min_coverage=MIN_LEXICAL_COVERAGE)


@lru_cache(maxsize=1)
def get_encounters() -> EncounterStore:
    """Separate database from get_store(): patient-specific data never shares a file with the knowledge base."""
    store = EncounterStore(ENCOUNTER_DB_PATH)
    if ENCOUNTER_TTL_HOURS > 0:
        store.purge_older_than(ENCOUNTER_TTL_HOURS * 3600)       # data minimisation at startup
    return store
