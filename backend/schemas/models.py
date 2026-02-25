"""Pydantic request/response models for the FastAPI backend."""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sources / Ingestion
# ---------------------------------------------------------------------------

class ProcessSourceRequest(BaseModel):
    source_id: str = Field(..., description="UUID of the source row to process.")


class ProcessSourceResponse(BaseModel):
    source_id: str
    chunk_count: int


# ---------------------------------------------------------------------------
# Semantic Search
# ---------------------------------------------------------------------------

class SemanticSearchRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID to search within.")
    query: str = Field(..., description="Natural-language query string.")
    match_count: int = Field(8, ge=1, le=50, description="Max chunks to return.")
    source_types: list[str] | None = Field(None, description="Filter by source_type values.")
    segment_tags: list[str] | None = Field(None, description="Filter by segment tags (overlap).")


class ChunkMatch(BaseModel):
    chunk_id: str
    source_id: str
    content: str
    metadata: dict
    similarity: float


class SemanticSearchResponse(BaseModel):
    matches: list[ChunkMatch]


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

class ConversationMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class RAGQueryRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID to search within.")
    query: str = Field(..., description="User question.")
    conversation_history: list[ConversationMessage] | None = Field(
        None, description="Previous conversation turns for multi-turn context."
    )
    match_count: int = Field(8, ge=1, le=50)
    source_types: list[str] | None = None
    segment_tags: list[str] | None = None


class RetrievedChunkPreview(BaseModel):
    chunk_id: str
    source_id: str
    similarity: float
    content_preview: str


class RAGQueryResponse(BaseModel):
    answer: str
    cited_chunk_ids: list[str]
    retrieved_chunks: list[RetrievedChunkPreview]
    usage: dict


# ---------------------------------------------------------------------------
# Synthesis — Theme Extraction (Pass 1)
# ---------------------------------------------------------------------------

class ThemeExtractionRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID.")
    source_ids: list[str] | None = Field(
        None, description="Restrict extraction to these source UUIDs. Defaults to all."
    )
    model_used: str | None = Field(None, description="Override model label stored in synthesis record.")


class ThemeExtractionResponse(BaseModel):
    synthesis_id: str
    themes: list[dict]
    theme_count: int


# ---------------------------------------------------------------------------
# Synthesis — Opportunity Scoring (Pass 2)
# ---------------------------------------------------------------------------

class OpportunityScoringRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID.")
    synthesis_id: str = Field(..., description="Synthesis record UUID from Pass 1.")
    theme_ids: list[str] | None = Field(
        None, description="Restrict scoring to these theme UUIDs. Defaults to all themes in synthesis."
    )


class OpportunityScoringResponse(BaseModel):
    synthesis_id: str
    opportunities: list[dict]
    opportunity_count: int
