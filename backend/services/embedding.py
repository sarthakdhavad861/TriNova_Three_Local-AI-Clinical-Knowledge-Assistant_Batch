"""
services/embedding.py
Singleton embedding service — reuses HTTP session, caches recent embeddings.
"""
import httpx
import asyncio
from functools import lru_cache
from config.settings import OLLAMA_BASE, EMBED_MODEL, OLLAMA_KEEPALIVE
from collections import OrderedDict
import hashlib, json

# LRU cache for embeddings (text → vector)
_EMBED_CACHE: OrderedDict = OrderedDict()
_EMBED_CACHE_MAX = 1000

# Persistent async HTTP client (reused across requests)
_client: httpx.AsyncClient = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=OLLAMA_BASE,
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )
    return _client


def _cache_key(texts: list[str]) -> str:
    return hashlib.md5(json.dumps(texts, sort_keys=True).encode()).hexdigest()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Cached per unique text batch."""
    key = _cache_key(texts)
    if key in _EMBED_CACHE:
        _EMBED_CACHE.move_to_end(key)
        return _EMBED_CACHE[key]

    client = _get_client()
    resp = await client.post(
        "/api/embed",
        json={"model": EMBED_MODEL, "input": texts, "keep_alive": OLLAMA_KEEPALIVE},
    )
    resp.raise_for_status()
    vectors = resp.json()["embeddings"]

    # Store in cache
    _EMBED_CACHE[key] = vectors
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)

    return vectors


async def embed_single(text: str) -> list[float]:
    """Embed one query string."""
    return (await embed_texts([text]))[0]


# Synchronous fallback for background tasks (non-async context)
def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    import requests as req
    resp = req.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": texts, "keep_alive": OLLAMA_KEEPALIVE},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]
