"""
Main.py — RAG Teaching Assistant FastAPI entry point v3
"""
import os, sys
from pathlib import Path

# Add backend dir to path so relative imports work
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import ensure_dirs
from api.routes import router

# Auto-create all required directories on startup
ensure_dirs()

app = FastAPI(
    title="RAG Teaching Assistant API",
    version="3.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# CORS — Phase 5: default to the local dev frontends only (was "*"). Patient data sits behind a secret per-encounter
# header token, but a wildcard origin would let any web page the doctor visits talk to the local API. No cookies are used.
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Encounter-Token", "X-Request-ID"],
    expose_headers=["X-Sources", "X-Video", "X-Web-Sources", "X-Intent", "X-Model", "X-Request-ID"],
)

# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"]        = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/encounters"):
        resp.headers["Cache-Control"] = "no-store"          # patient data must not be cached by browsers/proxies
    rid = request.headers.get("X-Request-ID", "")
    if rid:
        resp.headers["X-Request-ID"] = rid
    return resp

# Mount routes
app.include_router(router)

# Global error handler — Phase 5: never echo exception text (it can contain query or patient text) and never log it
@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "Main:app",
        host=os.getenv("HOST", "127.0.0.1"),          # local-only by default; set HOST=0.0.0.0 deliberately (e.g. in Docker)
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
        workers=1,
        loop="asyncio",
    )
