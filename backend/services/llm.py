"""
services/llm.py
Streaming client for the local Ollama /api/generate endpoint.
Prompt construction lives in knowledge/answer.py; this module only transports a finished prompt.
Sampling parameters are sent inside `options` (where Ollama reads them).
"""
import json
from typing import AsyncGenerator

import httpx

from config.settings import (
    OLLAMA_BASE, LLM_TEMPERATURE, OLLAMA_KEEPALIVE, LLM_NUM_CTX, LLM_NUM_PREDICT, resolve_model,
)

_client: httpx.AsyncClient = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=OLLAMA_BASE,
            timeout=httpx.Timeout(connect=8.0, read=120.0, write=30.0, pool=5.0),
        )
    return _client


def build_payload(prompt: str, ollama_model: str) -> dict:
    return {
        "model":      ollama_model,
        "prompt":     prompt,
        "stream":     True,
        "keep_alive": OLLAMA_KEEPALIVE,
        "options":    {"temperature": LLM_TEMPERATURE, "num_ctx": LLM_NUM_CTX, "num_predict": LLM_NUM_PREDICT},
    }


async def stream_prompt(prompt: str, model_alias: str | None = None) -> AsyncGenerator[str, None]:
    """Streams tokens for an already-built prompt. Raises RuntimeError with an actionable message on failure."""
    ollama_model = resolve_model(model_alias)
    client       = _get_client()
    try:
        async with client.stream("POST", "/api/generate", json=build_payload(prompt, ollama_model)) as resp:
            if resp.status_code == 404:
                raise RuntimeError(f"Ollama model not found: '{ollama_model}'. Run: ollama pull {ollama_model}")
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {resp.status_code}. "
                                   "Check that Ollama is running and the model is pulled.")
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data  = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    break
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to Ollama at {OLLAMA_BASE}. Make sure Ollama is running: ollama serve")
    except httpx.TimeoutException:
        raise RuntimeError("Ollama request timed out. The model may be overloaded or not responding.")
    except httpx.RemoteProtocolError:
        raise RuntimeError("Ollama closed the connection unexpectedly. Try again.")
