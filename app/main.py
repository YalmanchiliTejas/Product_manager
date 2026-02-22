from __future__ import annotations

import logging
import os
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ActionRequest,
    AdminConnectRequest,
    InterviewIngestRequest,
    MultiAgentStartRequest,
    SourceFetchRequest,
    SSOLoginRequest,
)
from .platform_service import PlatformService

logger = logging.getLogger(__name__)

app = FastAPI(title="PM AI Agent Backend", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize service — if an LLM API key is set, enable real AI pipeline
_llm = None
if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
    try:
        from .llm import create_provider
        _llm = create_provider()
        logger.info("LLM provider initialized: %s", type(_llm).__name__)
    except Exception as exc:
        logger.warning("Failed to initialize LLM provider, using fallback: %s", exc)

service = PlatformService(llm=_llm)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": service._llm is not None,
        "version": "0.5.0",
    }


# ------------------------------------------------------------------
# Auth & SSO
# ------------------------------------------------------------------

@app.get("/auth/sso/providers")
def sso_providers() -> dict:
    return {"providers": service.supported_identity_providers()}


@app.post("/auth/sso/login")
def sso_login(payload: SSOLoginRequest) -> dict:
    try:
        session = service.sso_login(payload)
        integrations = service.get_org_integrations(session.org_domain)
        needs_admin = not any(item.connected for item in integrations)
        return {
            "session": asdict(session),
            "org_integrations": [asdict(i) for i in integrations],
            "admin_action_required": needs_admin,
            "supported_sso_providers": service.supported_identity_providers(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------------
# Integration management
# ------------------------------------------------------------------

@app.post("/org/integrations/admin/connect")
def connect_org_integration(session_id: str, payload: AdminConnectRequest) -> dict:
    try:
        state = service.connect_org_integration(session_id, payload)
        return {"integration": asdict(state), "status": "connected"}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/org/integrations/status/{org_domain}")
def integration_status(org_domain: str) -> dict:
    return {
        "org_domain": org_domain,
        "integrations": [asdict(i) for i in service.get_org_integrations(org_domain)],
    }


@app.post("/actions/authorize")
def authorize_action(payload: ActionRequest) -> dict:
    try:
        return service.authorize_action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/consent/{integration}")
def grant_consent(integration: str, session_id: str) -> dict:
    try:
        service.grant_consent(session_id, integration)
        return {"session_id": session_id, "integration": integration, "consent_granted": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ------------------------------------------------------------------
# Source context fetching
# ------------------------------------------------------------------

@app.post("/sources/fetch")
def fetch_sources(payload: SourceFetchRequest) -> dict:
    """Pull documents from connected Slack/Confluence for agent consumption."""
    try:
        return service.fetch_source_context(
            session_id=payload.session_id,
            slack_sources=payload.slack_sources,
            confluence_sources=payload.confluence_sources,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------------
# Multi-agent workflow
# ------------------------------------------------------------------

@app.post("/multi-agent/start")
def start_multi_agent_workflow(payload: MultiAgentStartRequest) -> dict:
    """Start the full AI agent pipeline: context -> research -> design -> PRD -> tickets."""
    try:
        return service.start_multi_agent_workflow(
            session_id=payload.session_id,
            product_name=payload.product_name,
            documents=payload.documents,
            interview_notes=payload.interview_notes,
            target_integrations=payload.target_integrations,
            slack_sources=payload.slack_sources,
            confluence_sources=payload.confluence_sources,
            design_input=payload.design_input,
            stakeholder_roles=payload.stakeholder_roles,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/multi-agent/runs/{run_id}")
def get_multi_agent_run(run_id: str) -> dict:
    try:
        return service.workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/multi-agent/interviews/ingest")
def ingest_interview_feedback(payload: InterviewIngestRequest) -> dict:
    try:
        run = service.ingest_interview_feedback(payload.run_id, payload.notes)
        return {"run": run, "status": "updated"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
