from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from .models import (
    ActionRequest,
    AdminConnectRequest,
    IntegrationConnectionState,
    SSOLoginRequest,
    SUPPORTED_IDENTITY_PROVIDERS,
    SUPPORTED_INTEGRATIONS,
    SessionContext,
)

WRITE_PREFIXES = ("create", "comment", "edit", "post", "dm")
READ_SCOPES = {
    "jira": ["read:jira-work", "read:jira-user"],
    "confluence": ["read:confluence-content.summary", "read:confluence-content.all"],
    "slack": ["channels:read", "channels:history", "users:read"],
    "teams": ["User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"],
}


class PlatformService:
    """In-memory orchestration service used by API routes and unit tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._org_integrations: dict[str, dict[str, IntegrationConnectionState]] = {}
        self._user_consents: dict[tuple[str, str], bool] = {}
        self._workflow_runs: dict[str, dict[str, Any]] = {}

    def supported_identity_providers(self) -> list[str]:
        return list(SUPPORTED_IDENTITY_PROVIDERS)

    def sso_login(self, payload: SSOLoginRequest) -> SessionContext:
        provider = payload.provider.lower().strip()
        if provider not in SUPPORTED_IDENTITY_PROVIDERS:
            raise ValueError(f"Unsupported identity provider: {payload.provider}")
        if "@" not in payload.email:
            raise ValueError("Invalid email for SSO login")

        org_domain = payload.email.split("@", 1)[1].lower()
        session = SessionContext(
            session_id=secrets.token_urlsafe(18),
            email=payload.email.lower(),
            full_name=payload.full_name,
            is_admin=payload.is_admin,
            org_domain=org_domain,
            provider=provider,
        )
        self._sessions[session.session_id] = session
        self._org_integrations.setdefault(org_domain, self._empty_org_integrations(org_domain))
        return session

    def get_org_integrations(self, org_domain: str) -> list[IntegrationConnectionState]:
        rows = self._org_integrations.setdefault(org_domain, self._empty_org_integrations(org_domain))
        return [rows[name] for name in SUPPORTED_INTEGRATIONS]

    def connect_org_integration(self, session_id: str, payload: AdminConnectRequest) -> IntegrationConnectionState:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError("Invalid session")
        if not session.is_admin:
            raise PermissionError("Only admins can connect org integrations")
        if payload.org_domain != session.org_domain:
            raise PermissionError("Admin can connect integrations only for their own organization")

        integration = payload.integration.lower().strip()
        if integration not in SUPPORTED_INTEGRATIONS:
            raise ValueError(f"Unsupported integration: {payload.integration}")

        state = IntegrationConnectionState(
            org_domain=payload.org_domain,
            integration=integration,
            connected=True,
            scopes=list(payload.scopes or READ_SCOPES.get(integration, [])),
            connected_by=session.email,
        )
        self._org_integrations.setdefault(payload.org_domain, self._empty_org_integrations(payload.org_domain))[integration] = state
        return state

    def authorize_action(self, payload: ActionRequest) -> dict[str, Any]:
        session = self._sessions.get(payload.session_id)
        if not session:
            raise ValueError("Invalid session")

        integration = payload.integration.lower().strip()
        if integration not in SUPPORTED_INTEGRATIONS:
            raise ValueError(f"Unsupported integration: {payload.integration}")

        org_state = self._org_integrations.setdefault(session.org_domain, self._empty_org_integrations(session.org_domain))[integration]
        if not org_state.connected:
            return {"allowed": False, "consent_required": False, "reason": f"Org integration not connected for {integration}"}

        needs_write = payload.action.lower().startswith(WRITE_PREFIXES)
        consent_given = self._user_consents.get((payload.session_id, integration), False)
        if needs_write and not consent_given:
            return {
                "allowed": False,
                "consent_required": True,
                "reason": "User delegated write consent required",
                "consent_url": f"/consent/{integration}?session_id={payload.session_id}",
            }

        return {"allowed": True, "consent_required": False, "mode": "org_app", "reason": "Authorized"}

    def grant_consent(self, session_id: str, integration: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("Invalid session")
        normalized = integration.lower().strip()
        if normalized not in SUPPORTED_INTEGRATIONS:
            raise ValueError(f"Unsupported integration: {integration}")
        self._user_consents[(session_id, normalized)] = True

    def start_multi_agent_workflow(
        self,
        session_id: str,
        product_name: str,
        documents: list[str],
        interview_notes: list[str],
        target_integrations: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError("Invalid session")

        normalized_docs = [d.strip() for d in documents if d and d.strip()]
        normalized_feedback = [n.strip() for n in interview_notes if n and n.strip()]
        run_id = secrets.token_urlsafe(10)

        pipeline = self._execute_agent_pipeline(
            product_name=product_name,
            documents=normalized_docs,
            feedback=normalized_feedback,
            target_integrations=target_integrations or ["jira", "slack"],
        )
        run = {
            "run_id": run_id,
            "session_id": session_id,
            "org_domain": session.org_domain,
            "product_name": product_name,
            "rlms_context": pipeline["rlms_context"],
            "interview_plan": pipeline["interview_plan"],
            "prd": pipeline["prd"],
            "tickets": pipeline["tickets"],
            "distribution": pipeline["distribution"],
            "pm_ops": self._pm_operations_checklist(),
            "model_strategy": self._model_strategy_note(),
            "agent_plan": self._agent_plan(),
            "orchestration": pipeline["orchestration"],
            "_source_documents": normalized_docs,
            "_source_feedback": normalized_feedback,
        }
        self._workflow_runs[run_id] = run
        return self._public_run(run)

    def workflow_run(self, run_id: str) -> dict[str, Any]:
        run = self._workflow_runs.get(run_id)
        if not run:
            raise ValueError("Unknown workflow run")
        return self._public_run(run)

    def ingest_interview_feedback(self, run_id: str, notes: list[str]) -> dict[str, Any]:
        run = self._workflow_runs.get(run_id)
        if not run:
            raise ValueError("Unknown workflow run")
        fresh_notes = [n.strip() for n in notes if n and n.strip()]
        if not fresh_notes:
            return self._public_run(run)

        updated_feedback = run.get("_source_feedback", []) + fresh_notes
        run["_source_feedback"] = updated_feedback
        pipeline = self._execute_agent_pipeline(
            product_name=run["product_name"],
            documents=run.get("_source_documents", []),
            feedback=updated_feedback,
            target_integrations=[item.get("integration", "jira") for item in run.get("distribution", [])],
        )
        run["rlms_context"] = pipeline["rlms_context"]
        run["interview_plan"] = pipeline["interview_plan"]
        run["tickets"] = pipeline["tickets"]
        run["prd"] = pipeline["prd"]
        run["distribution"] = pipeline["distribution"]
        run["orchestration"] = pipeline["orchestration"]
        return self._public_run(run)

    def _empty_org_integrations(self, org_domain: str) -> dict[str, IntegrationConnectionState]:
        return {
            name: IntegrationConnectionState(
                org_domain=org_domain,
                integration=name,
                connected=False,
                scopes=[],
                connected_by="",
            )
            for name in SUPPORTED_INTEGRATIONS
        }

    def _rlms_recursive_context(self, documents: list[str], feedback: list[str]) -> dict[str, Any]:
        chunks = self._chunk_documents(documents, chunk_size=700)
        lvl1 = [self._mini_summary(chunk, 160) for chunk in chunks]
        lvl2 = [self._mini_summary(" ".join(lvl1[i:i + 4]), 200) for i in range(0, len(lvl1), 4)]
        merged_input = " ".join(lvl2 + feedback)
        global_summary = self._mini_summary(merged_input, 240) if merged_input else "No source context provided."
        return {
            "documents_ingested": len(documents),
            "feedback_items": len(feedback),
            "chunk_count": len(chunks),
            "level_1_summaries": lvl1[:24],
            "level_2_summaries": lvl2[:12],
            "global_summary": global_summary,
            "token_policy": {
                "chunk_size_chars": 700,
                "recursion_levels": 2,
                "max_level_1_summaries": 24,
                "max_level_2_summaries": 12,
            },
        }

    def _chunk_documents(self, documents: list[str], chunk_size: int) -> list[str]:
        chunks: list[str] = []
        for doc in documents:
            for i in range(0, len(doc), chunk_size):
                chunk = doc[i:i + chunk_size]
                if chunk:
                    chunks.append(chunk)
        return chunks

    def _mini_summary(self, text: str, max_chars: int) -> str:
        clipped = " ".join(text.split())
        if len(clipped) <= max_chars:
            return clipped
        return clipped[: max_chars - 3] + "..."

    def _generate_prd(self, product_name: str, rlms_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": f"PRD: {product_name}",
            "problem_statement": f"Build {product_name} to solve fragmented PM workflows across discovery, planning, and delivery.",
            "goals": [
                "Ingest large documents and interviews with recursive context compression",
                "Generate structured PRDs and convert to execution-ready tickets",
                "Automate distribution across Jira/Slack/Confluence while preserving traceability",
            ],
            "non_goals": ["Replace human PM decision-making", "Autonomous production changes without approval"],
            "source_context": rlms_context.get("global_summary", ""),
        }

    def _convert_prd_to_tickets(self, product_name: str) -> list[dict[str, Any]]:
        key = (product_name or "PRD")[:3].upper()
        return [
            {"id": f"{key}-101", "title": "Set up document ingestion and RLMS recursion", "owner_role": "ML Engineer", "priority": "P0"},
            {"id": f"{key}-102", "title": "Implement interview outreach + feedback collector", "owner_role": "Product Ops", "priority": "P1"},
            {"id": f"{key}-103", "title": "Generate PRD and sync ticket graph", "owner_role": "PM", "priority": "P0"},
        ]

    def _distribute_tickets(self, integrations: list[str], tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enabled = [i for i in integrations if i in SUPPORTED_INTEGRATIONS] or ["jira"]
        return [{"integration": i, "ticket_count": len(tickets), "status": "queued"} for i in enabled]

    def _interview_plan(self) -> dict[str, Any]:
        return {
            "channels": ["email", "slack_dm", "calendar_link"],
            "question_bank": [
                "What is the biggest blocker in your current workflow?",
                "Where do requirements lose fidelity today?",
                "Which metrics define success for this initiative?",
            ],
        }

    def _pm_operations_checklist(self) -> list[str]:
        return [
            "Roadmap sequencing and dependency mapping",
            "Release planning + change-log generation",
            "Risk register updates and mitigation tracking",
            "Stakeholder communication drafts",
            "Experiment and KPI review cadences",
        ]

    def _model_strategy_note(self) -> dict[str, Any]:
        return {
            "dspy_recommended": True,
            "dspy_usage": "Use DSPy for prompt module optimization and evaluator loops over PRD/ticket quality.",
            "multi_model": [
                "Use a strong reasoning model for PRD synthesis",
                "Use lower-cost models for chunk summarization and extraction",
                "Cursor can be used as the coding client while this backend calls selected model APIs",
            ],
            "fine_tuning_note": "Start with retrieval + evaluators; fine-tune specialist models after collecting high-quality traces.",
        }


    def _agent_plan(self) -> list[dict[str, str]]:
        return [
            {"agent": "context-architect", "goal": "Chunk and recursively compress long documents to controllable context."},
            {"agent": "research-ops", "goal": "Send interview prompts, collect feedback, and normalize insights."},
            {"agent": "prd-writer", "goal": "Synthesize a PM-ready PRD draft with goals, non-goals, and metrics."},
            {"agent": "delivery-planner", "goal": "Convert PRD outcomes into tickets and distribute them to tools."},
        ]

    def _public_run(self, run: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in run.items() if not k.startswith("_")}

    def _execute_agent_pipeline(
        self,
        product_name: str,
        documents: list[str],
        feedback: list[str],
        target_integrations: list[str],
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        started_at = self._now_iso()

        rlms_context = self._rlms_recursive_context(documents, feedback)
        steps.append({"agent": "context-architect", "status": "completed", "output": "rlms_context"})

        interview_plan = self._interview_plan()
        steps.append({"agent": "research-ops", "status": "completed", "output": "interview_plan"})

        prd = self._generate_prd(product_name, rlms_context)
        steps.append({"agent": "prd-writer", "status": "completed", "output": "prd"})

        tickets = self._convert_prd_to_tickets(product_name)
        distribution = self._distribute_tickets(target_integrations, tickets)
        steps.append({"agent": "delivery-planner", "status": "completed", "output": "tickets+distribution"})

        orchestration = {
            "strategy": "openclaw-style staged planner",
            "started_at": started_at,
            "completed_at": self._now_iso(),
            "steps": steps,
        }

        return {
            "rlms_context": rlms_context,
            "interview_plan": interview_plan,
            "prd": prd,
            "tickets": tickets,
            "distribution": distribution,
            "orchestration": orchestration,
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
