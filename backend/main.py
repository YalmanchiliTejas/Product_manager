"""FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload --port 8000

API overview:
    # Projects
    GET    /api/projects                      — List projects (filter by user_id)
    POST   /api/projects                      — Create project
    GET    /api/projects/{id}                 — Get project
    PATCH  /api/projects/{id}                 — Update project
    DELETE /api/projects/{id}                 — Delete project + cascade

    # Sources
    GET    /api/sources?project_id=<id>       — List sources for a project
    POST   /api/sources                       — Create source
    GET    /api/sources/{id}                  — Get source
    PATCH  /api/sources/{id}                  — Update source
    DELETE /api/sources/{id}                  — Delete source + chunks
    POST   /api/sources/process               — Ingest: extract → chunk → embed → store

    # Search
    POST   /api/search/semantic               — pgvector semantic similarity search
    POST   /api/search/rag                    — RAG: memory recall + retrieve + generate

    # Synthesis
    POST   /api/synthesis/themes              — Pass 1: theme extraction (fast model)
    POST   /api/synthesis/opportunities       — Pass 2: opportunity scoring (strong model)
    POST   /api/synthesis/run                 — Full LangGraph pipeline: Pass 1 + Pass 2
                                                + recursive evidence drilling

    # Memory (mem0 persistent PM memory)
    POST   /api/memory/add                    — Extract + store memories from conversation
    POST   /api/memory/search                 — Semantic search over PM memories
    GET    /api/memory/{project_id}/{user_id} — List all memories for a project/user
    DELETE /api/memory/{memory_id}            — Delete a specific memory

    # Interview Agent
    POST   /api/interview/sessions              — Create interview session
    GET    /api/interview/sessions/{id}         — Get session state
    POST   /api/interview/sessions/{id}/ask     — Submit a question
    POST   /api/interview/sessions/{id}/confirm — Confirm/reject tasks
    POST   /api/interview/sessions/{id}/review  — Approve/revise PRD
    GET    /api/interview/sessions/{id}/tasks   — Get task list
    GET    /api/interview/sessions/{id}/prd     — Get generated PRD
    GET    /api/interview/sessions/{id}/tickets — Get generated tickets

    GET    /health                            — Liveness check
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import interview, memory, projects, search, sources, synthesis

app = FastAPI(
    title="Product Manager AI Backend",
    description=(
        "Python LLM service providing project/source management, file ingestion, "
        "semantic search, RAG with persistent memory (mem0), theme extraction, "
        "opportunity scoring, and a full LangGraph synthesis pipeline with "
        "recursive evidence drilling."
    ),
    version="2.0.0",
)

# Allow requests from the Next.js frontend (and any other origin in dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(search.router)
app.include_router(synthesis.router)
app.include_router(memory.router)
app.include_router(interview.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe — returns 200 when the service is up."""
    return {"status": "ok"}
