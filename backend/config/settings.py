import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

DIRS = ["uploads", "data", "vectorstore/chroma_db"]

OLLAMA_BASE      = os.getenv("OLLAMA_BASE",       "http://localhost:11434")
EMBED_MODEL      = os.getenv("EMBED_MODEL",       "bge-m3")
OLLAMA_KEEPALIVE = os.getenv("OLLAMA_KEEPALIVE",  "5m")

TOP_K            = int(os.getenv("TOP_K",             "6"))
SIM_THRESHOLD    = float(os.getenv("SIM_THRESHOLD",   "0.25"))   # min dense cosine similarity; calibrate with `knowledge.eval`
MIN_LEXICAL_COVERAGE = float(os.getenv("MIN_LEXICAL_COVERAGE", "0.5"))  # share of query terms a keyword hit must contain
RETRIEVE_OVERFETCH   = int(os.getenv("RETRIEVE_OVERFETCH",     "4"))    # candidates fetched per channel = TOP_K x this
MAX_CTX_CHUNKS   = int(os.getenv("MAX_CTX_CHUNKS",    "5"))      # excerpts passed to the LLM
MAX_CONTEXT_WORDS = int(os.getenv("MAX_CONTEXT_WORDS", "1400"))  # whole chunks only; extra chunks are dropped, never cut
LLM_TEMPERATURE  = float(os.getenv("LLM_TEMPERATURE", "0.1"))    # low: this is a reference tool, not a creative one
LLM_NUM_CTX      = int(os.getenv("LLM_NUM_CTX",      "4096"))
LLM_NUM_PREDICT  = int(os.getenv("LLM_NUM_PREDICT",  "600"))

CHROMA_PATH       = str(BASE_DIR / "vectorstore" / "chroma_db")
CHROMA_COLLECTION = "rag_chunks"

# ── Medical knowledge ingestion (Phase 2) ─────────────────────────────────────
KNOWLEDGE_DB_PATH = os.getenv("KNOWLEDGE_DB_PATH", str(BASE_DIR / "data" / "knowledge.db"))
# Phase 5 — patient-encounter data lives in its OWN database file, never in the shared knowledge base
ENCOUNTER_DB_PATH = os.getenv("ENCOUNTER_DB_PATH", str(BASE_DIR / "data" / "encounters.db"))
ENCOUNTER_TTL_HOURS = float(os.getenv("ENCOUNTER_TTL_HOURS", "24"))   # idle encounters are erased; 0 disables expiry
ALLOWED_DOC_EXTS  = {".pdf", ".txt", ".md", ".markdown", ".csv", ".json"}
MAX_DOC_BYTES     = int(os.getenv("MAX_DOC_BYTES",     str(50 * 1024**2)))
CHUNK_MAX_WORDS   = int(os.getenv("CHUNK_MAX_WORDS",   "180"))
EMBED_BATCH       = int(os.getenv("EMBED_BATCH",       "32"))

# ── Multi-model config ────────────────────────────────────────────────────────
# DEFAULT_LLM: which model alias to use when none is specified ("llama" or "qwen")
DEFAULT_LLM        = os.getenv("DEFAULT_LLM",        "llama")
LLM_MODEL_LLAMA    = os.getenv("LLM_MODEL_LLAMA",    "llama3.1:latest")
LLM_MODEL_QWEN     = os.getenv("LLM_MODEL_QWEN",     "qwen2.5:3b")

# Centralised registry — add new models here only
MODEL_REGISTRY: dict[str, dict] = {
    "llama": {"id": "llama", "label": "Llama 3.1",    "model": LLM_MODEL_LLAMA},
    "qwen":  {"id": "qwen",  "label": "Qwen 2.5 3B",  "model": LLM_MODEL_QWEN},
}

def resolve_model(alias: str | None) -> str:
    """
    Converts a frontend alias ("llama", "qwen", None) to the Ollama model name.
    Raises ValueError for unknown aliases so the API can return a clean 400.
    """
    if not alias:
        alias = DEFAULT_LLM
    alias = alias.strip().lower()
    if alias not in MODEL_REGISTRY:
        allowed = list(MODEL_REGISTRY.keys())
        raise ValueError(f"Unknown model '{alias}'. Allowed: {allowed}. "
                         f"Check DEFAULT_LLM in .env or send one of: {allowed}")
    return MODEL_REGISTRY[alias]["model"]

# Keep LLM_MODEL as backward-compat alias (used nowhere new, but safe)
LLM_MODEL = resolve_model(DEFAULT_LLM)

def ensure_dirs():
    for d in DIRS:
        (BASE_DIR / d).mkdir(parents=True, exist_ok=True)
