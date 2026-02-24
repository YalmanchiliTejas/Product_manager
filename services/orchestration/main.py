"""
Beacon Orchestration Service
────────────────────────────
FastAPI service that handles all AI workloads:
  POST /process          — chunk + embed + store a source
  POST /synthesize       — run MapReduce synthesis pipeline
  POST /chat/stream      — streaming RAG chat response
  POST /search           — semantic search over project chunks

Run locally:
  uvicorn services.orchestration.main:app --reload --port 8000

Environment variables (see config.py for full list):
  LLM_FAST_MODEL        default: claude-haiku-4-5-20251001
  LLM_BALANCED_MODEL    default: claude-sonnet-4-5
  LLM_DEEP_MODEL        default: claude-opus-4-5
  EMBEDDING_MODEL       default: text-embedding-3-small
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  ANTHROPIC_API_KEY     (or OPENAI_API_KEY / GEMINI_API_KEY etc.)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.orchestration.routes.process import router as process_router
from services.orchestration.routes.synthesize import router as synthesize_router
from services.orchestration.routes.chat import router as chat_router
from services.orchestration.routes.search import router as search_router

app = FastAPI(
    title="Beacon Orchestration",
    description="LLM-agnostic AI pipeline for product discovery synthesis",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(process_router)
app.include_router(synthesize_router)
app.include_router(chat_router)
app.include_router(search_router)


@app.get("/health")
def health():
    return {"status": "ok"}
