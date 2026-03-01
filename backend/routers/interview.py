"""Interview Agent API router.

Provides endpoints for creating and interacting with interview analysis
sessions.  Each session manages a stateful orchestrator graph that can
be paused and resumed at human-in-the-loop interrupt points.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.agents.orchestrator import InterviewSession
from backend.agents.memory_hooks import persist_session_to_memory
from backend.schemas.models import (
    InterviewAskRequest,
    InterviewConfirmRequest,
    InterviewReviewRequest,
    InterviewSessionCreate,
    InterviewSessionResponse,
)

router = APIRouter(prefix="/api/interview", tags=["interview"])

# In-memory session store (production would use DB + Redis)
_sessions: dict[str, InterviewSession] = {}


def _get_session(session_id: str) -> InterviewSession:
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    return session


def _session_response(session: InterviewSession) -> dict:
    state = session.state
    return {
        "session_id": state["session_id"],
        "project_id": state["project_id"],
        "user_id": state["user_id"],
        "phase": state["phase"],
        "tasks": state.get("tasks", []),
        "messages": state.get("messages", []),
        "prd_document": state.get("prd_document") or None,
        "tickets": state.get("tickets") or None,
    }


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=InterviewSessionResponse)
def create_session(req: InterviewSessionCreate):
    """Create a new interview analysis session and run intake."""
    session = InterviewSession(
        interview_data=req.interview_data,
        market_context=req.market_context,
        project_id=req.project_id,
        user_id=req.user_id,
    )
    session.start()
    _sessions[session.state["session_id"]] = session
    return _session_response(session)


@router.get("/sessions/{session_id}", response_model=InterviewSessionResponse)
def get_session(session_id: str):
    """Get the current state of a session."""
    session = _get_session(session_id)
    return _session_response(session)


@router.post("/sessions/{session_id}/ask", response_model=InterviewSessionResponse)
def ask_question(session_id: str, req: InterviewAskRequest):
    """Submit a question to the interview agent."""
    session = _get_session(session_id)
    session.ask(req.question, auto_confirm=req.auto_confirm)
    return _session_response(session)


@router.post("/sessions/{session_id}/confirm", response_model=InterviewSessionResponse)
def confirm_tasks(session_id: str, req: InterviewConfirmRequest):
    """Confirm or reject the proposed task list."""
    session = _get_session(session_id)
    session.confirm(req.response)
    return _session_response(session)


@router.post("/sessions/{session_id}/review", response_model=InterviewSessionResponse)
def review_prd(session_id: str, req: InterviewReviewRequest):
    """Approve or request revision of the generated PRD."""
    session = _get_session(session_id)
    session.review_prd(req.response)
    return _session_response(session)


@router.get("/sessions/{session_id}/tasks")
def get_tasks(session_id: str):
    """Get the current task list for a session."""
    session = _get_session(session_id)
    return {"tasks": session.get_tasks()}


@router.get("/sessions/{session_id}/prd")
def get_prd(session_id: str):
    """Get the generated PRD for a session."""
    session = _get_session(session_id)
    prd = session.get_prd()
    if not prd:
        raise HTTPException(status_code=404, detail="No PRD generated yet.")
    return prd


@router.get("/sessions/{session_id}/tickets")
def get_tickets(session_id: str):
    """Get the generated tickets for a session."""
    session = _get_session(session_id)
    tickets = session.get_tickets()
    if not tickets:
        raise HTTPException(status_code=404, detail="No tickets generated yet.")
    return {"tickets": tickets}


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str):
    """Explicitly end a session and persist all memories.

    Triggers Hook 3: feeds the full conversation to mem0, runs
    consolidation + supersede on memory_items, and rebuilds the
    compact index. Call this when the user is done with the session.
    """
    session = _get_session(session_id)
    stats = persist_session_to_memory(session.state)
    return {
        "session_id": session_id,
        "status": "ended",
        "memory_stats": stats,
    }
