"""FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload --port 8000

API overview:
    POST /api/sources/process          — Ingest: extract → chunk → embed → store
    POST /api/search/semantic          — pgvector semantic similarity search
    POST /api/search/rag               — RAG: retrieve + generate grounded answer
    POST /api/synthesis/themes         — Pass 1: theme extraction (fast model)
    POST /api/synthesis/opportunities  — Pass 2: opportunity scoring (strong model)
    GET  /health                       — Liveness check
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import search, sources, synthesis

app = FastAPI(
    title="Product Manager AI Backend",
    description=(
        "Python LLM service providing file ingestion, semantic search, RAG, "
        "theme extraction, and opportunity scoring pipelines."
    ),
    version="1.0.0",
)

# Allow requests from the Next.js frontend (and any other origin in dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources.router)
app.include_router(search.router)
app.include_router(synthesis.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe — returns 200 when the service is up."""
    return {"status": "ok"}
