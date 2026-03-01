"""Pydantic request/response models for the FastAPI backend."""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    user_id: str = Field(..., description="Auth user UUID who owns this project.")
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Sources CRUD
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    project_id: str = Field(..., description="Parent project UUID.")
    name: str = Field(..., min_length=1, max_length=300)
    source_type: str = Field(
        ...,
        description="One of: interview, support_ticket, nps, survey, analytics, other",
    )
    segment_tags: list[str] | None = None
    raw_content: str | None = None
    file_path: str | None = None
    metadata: dict | None = None


class SourceUpdate(BaseModel):
    source_type: str | None = None
    segment_tags: list[str] | None = None


class SourceResponse(BaseModel):
    id: str
    project_id: str
    name: str
    source_type: str
    segment_tags: list[str] | None
    raw_content: str | None
    file_path: str | None
    metadata: dict | None
    created_at: str


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
    user_id: str | None = Field(
        None,
        description="PM user UUID. When provided, relevant memories are injected into "
        "context and this exchange is stored for future sessions.",
    )
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


# ---------------------------------------------------------------------------
# Synthesis — LangGraph full-pipeline (Pass 1 + Pass 2 + recursive drill-down)
# ---------------------------------------------------------------------------

class SynthesisGraphRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID.")
    source_ids: list[str] | None = Field(
        None, description="Restrict to these source UUIDs. Defaults to all."
    )
    model_used: str | None = Field(None, description="Override model label in synthesis record.")
    max_drill_down_iterations: int = Field(
        2,
        ge=0,
        le=5,
        description=(
            "How many recursive evidence-drilling passes to allow for weak themes. "
            "0 = single-pass (same as original pipeline). "
            "Higher = more thorough but slower."
        ),
    )


class SynthesisGraphResponse(BaseModel):
    synthesis_id: str
    themes: list[dict]
    opportunities: list[dict]
    iterations: int = Field(..., description="Number of drill-down iterations actually performed.")
    theme_count: int
    opportunity_count: int


# ---------------------------------------------------------------------------
# Memory — persistent PM memory via mem0
# ---------------------------------------------------------------------------

class MemoryAddRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID (scopes memories to this project).")
    user_id: str = Field(..., description="PM user UUID.")
    messages: list[ConversationMessage] = Field(
        ..., description="Conversation turns to extract memories from."
    )


class MemorySearchRequest(BaseModel):
    project_id: str
    user_id: str
    query: str = Field(..., description="Natural language query to search memories against.")
    limit: int = Field(5, ge=1, le=20)


class MemoryItem(BaseModel):
    id: str
    memory: str
    score: float | None = None
    created_at: str | None = None
    metadata: dict | None = None


class MemoryResponse(BaseModel):
    memories: list[MemoryItem]


class ContextPackRequest(BaseModel):
    project_id: str
    task_type: str = Field(..., description="Task category (e.g., prd_generation).")
    query: str
    budget_tokens: int = Field(2500, ge=200, le=12000)


class ContextPackResponse(BaseModel):
    index: str
    memory_items: list[dict]
    evidence_chunks: list[dict]
    citations: dict


# ---------------------------------------------------------------------------
# Interview Agent
# ---------------------------------------------------------------------------

class InterviewSessionCreate(BaseModel):
    project_id: str = Field(..., description="Parent project UUID.")
    user_id: str = Field(..., description="PM user UUID.")
    interview_data: list[dict] = Field(
        default_factory=list,
        description="Pre-parsed interview documents [{filename, content, chunks, metadata}].",
    )
    market_context: str = Field("", description="Free-text market context.")


class InterviewSessionResponse(BaseModel):
    session_id: str
    project_id: str
    user_id: str
    phase: str
    tasks: list[dict]
    messages: list[dict]
    prd_document: dict | None = None
    tickets: list[dict] | None = None


class InterviewAskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The PM's question or directive.")
    auto_confirm: bool = Field(
        False,
        description="If true, auto-confirm proposed tasks without waiting.",
    )


class InterviewConfirmRequest(BaseModel):
    response: str = Field(
        "yes",
        description="Confirmation: 'yes', 'no', or modification text.",
    )


class InterviewReviewRequest(BaseModel):
    response: str = Field(
        "approve",
        description="PRD review: 'approve', 'skip', or revision feedback.",
    )


class TaskItemResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: int
    agent: str
    output: dict | None = None


class PRDDocumentResponse(BaseModel):
    title: str
    problem_statement: str
    user_stories: list[str]
    proposed_solution: str
    kpis: list[dict]
    technical_requirements: list[str]
    constraints_and_risks: list[str]
    next_actions: list[dict]
    full_markdown: str
    cited_chunk_ids: list[str]
    cited_memory_ids: list[str]


class TicketResponse(BaseModel):
    id: str
    ticket_type: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: str
    estimated_points: int | None = None
    parent_id: str | None = None
    labels: list[str]
