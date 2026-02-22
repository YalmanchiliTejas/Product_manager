from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from .agents import (
    ContextArchitect,
    DeliveryPlanner,
    DesignReasoner,
    PRDWriter,
    ResearchOps,
)
from .integrations import ConfluenceClient, SlackClient
from .llm import ImageInput, create_provider
from .llm.base import LLMProvider
from .models import (
    ActionRequest,
    AdminConnectRequest,
    ConfluenceSourceConfig,
    DesignInput,
    IntegrationConnectionState,
    SlackSourceConfig,
    SSOLoginRequest,
    SUPPORTED_IDENTITY_PROVIDERS,
    SUPPORTED_INTEGRATIONS,
    SessionContext,
)

logger = logging.getLogger(__name__)

WRITE_PREFIXES = ("create", "comment", "edit", "post", "dm")
READ_SCOPES = {
    "jira": ["read:jira-work", "read:jira-user"],
    "confluence": ["read:confluence-content.summary", "read:confluence-content.all"],
    "slack": ["channels:read", "channels:history", "users:read"],
    "teams": ["User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"],
}


class PlatformService:
    """Orchestration service that connects SSO, integrations, and the AI agent pipeline.

    The service manages two concerns:
    1. Auth & integrations (SSO login, org integration connect, consent)
    2. Multi-agent workflow (context ingestion -> research -> PRD -> design -> delivery)

    When an LLM provider is available, agents make real AI calls.
    When no provider is configured (e.g. in tests), agents fall back to
    deterministic mock behavior so the pipeline shape is always testable.
    """

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._org_integrations: dict[str, dict[str, IntegrationConnectionState]] = {}
        self._user_consents: dict[tuple[str, str], bool] = {}
        self._workflow_runs: dict[str, dict[str, Any]] = {}

        # LLM provider — None means use deterministic fallback (for tests)
        self._llm = llm

        # Integration clients — initialized lazily when tokens are available
        self._slack: SlackClient | None = None
        self._confluence: ConfluenceClient | None = None

    # ------------------------------------------------------------------
    # Auth & integrations (unchanged from original)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Source context fetching (new — pulls from real Slack/Confluence)
    # ------------------------------------------------------------------

    def fetch_source_context(
        self,
        session_id: str,
        slack_sources: SlackSourceConfig | None = None,
        confluence_sources: ConfluenceSourceConfig | None = None,
    ) -> dict[str, Any]:
        """Fetch documents from connected integrations for agent consumption."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError("Invalid session")

        documents: list[str] = []
        sources_used: list[str] = []

        if slack_sources and self._slack:
            slack_docs = self._slack.fetch_context_for_agent(
                channel_ids=slack_sources.channel_ids,
                thread_refs=slack_sources.thread_refs,
                search_queries=slack_sources.search_queries,
            )
            documents.extend(slack_docs)
            sources_used.append(f"slack:{len(slack_docs)} documents")

        if confluence_sources and self._confluence:
            conf_docs = self._confluence.fetch_context_for_agent(
                page_ids=confluence_sources.page_ids,
                search_queries=confluence_sources.search_queries,
                space_keys=confluence_sources.space_keys,
                labels=confluence_sources.labels,
            )
            documents.extend(conf_docs)
            sources_used.append(f"confluence:{len(conf_docs)} documents")

        return {
            "documents": documents,
            "sources_used": sources_used,
            "total_documents": len(documents),
        }

    # ------------------------------------------------------------------
    # Multi-agent workflow
    # ------------------------------------------------------------------

    def start_multi_agent_workflow(
        self,
        session_id: str,
        product_name: str,
        documents: list[str],
        interview_notes: list[str],
        target_integrations: Optional[list[str]] = None,
        slack_sources: Optional[SlackSourceConfig] = None,
        confluence_sources: Optional[ConfluenceSourceConfig] = None,
        design_input: Optional[DesignInput] = None,
        stakeholder_roles: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError("Invalid session")

        normalized_docs = [d.strip() for d in documents if d and d.strip()]
        normalized_feedback = [n.strip() for n in interview_notes if n and n.strip()]

        # Pull additional docs from connected integrations
        if slack_sources or confluence_sources:
            fetched = self.fetch_source_context(session_id, slack_sources, confluence_sources)
            normalized_docs.extend(fetched["documents"])

        run_id = secrets.token_urlsafe(10)

        pipeline = self._execute_agent_pipeline(
            product_name=product_name,
            documents=normalized_docs,
            feedback=normalized_feedback,
            target_integrations=target_integrations or ["jira", "slack"],
            design_input=design_input,
            stakeholder_roles=stakeholder_roles,
        )
        run = {
            "run_id": run_id,
            "session_id": session_id,
            "org_domain": session.org_domain,
            "product_name": product_name,
            "rlms_context": pipeline["rlms_context"],
            "interview_plan": pipeline["interview_plan"],
            "prd": pipeline["prd"],
            "design_analysis": pipeline.get("design_analysis"),
            "tickets": pipeline["tickets"],
            "distribution": pipeline["distribution"],
            "pm_ops": self._pm_operations_checklist(),
            "model_strategy": self._model_strategy_note(),
            "agent_plan": self._agent_plan(),
            "orchestration": pipeline["orchestration"],
            "_source_documents": normalized_docs,
            "_source_feedback": normalized_feedback,
            "_design_input": design_input,
            "_stakeholder_roles": stakeholder_roles,
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
            design_input=run.get("_design_input"),
            stakeholder_roles=run.get("_stakeholder_roles"),
        )
        run["rlms_context"] = pipeline["rlms_context"]
        run["interview_plan"] = pipeline["interview_plan"]
        run["tickets"] = pipeline["tickets"]
        run["prd"] = pipeline["prd"]
        run["design_analysis"] = pipeline.get("design_analysis")
        run["distribution"] = pipeline["distribution"]
        run["orchestration"] = pipeline["orchestration"]
        return self._public_run(run)

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    def _execute_agent_pipeline(
        self,
        product_name: str,
        documents: list[str],
        feedback: list[str],
        target_integrations: list[str],
        design_input: Optional[DesignInput] = None,
        stakeholder_roles: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        started_at = self._now_iso()

        if self._llm:
            return self._execute_llm_pipeline(
                product_name=product_name,
                documents=documents,
                feedback=feedback,
                target_integrations=target_integrations,
                design_input=design_input,
                stakeholder_roles=stakeholder_roles,
                steps=steps,
                started_at=started_at,
            )
        else:
            return self._execute_fallback_pipeline(
                product_name=product_name,
                documents=documents,
                feedback=feedback,
                target_integrations=target_integrations,
                steps=steps,
                started_at=started_at,
            )

    def _execute_llm_pipeline(
        self,
        product_name: str,
        documents: list[str],
        feedback: list[str],
        target_integrations: list[str],
        design_input: Optional[DesignInput],
        stakeholder_roles: Optional[list[str]],
        steps: list[dict[str, Any]],
        started_at: str,
    ) -> dict[str, Any]:
        """Run the full agent pipeline with real LLM calls."""

        # 1. Context Architect — RLMS recursive summarization
        context_agent = ContextArchitect(self._llm)
        ctx_result = context_agent.run(documents=documents, feedback=feedback)
        rlms_context = ctx_result.output
        steps.append(ctx_result.to_dict())

        global_summary = rlms_context.get("global_summary", "")
        feedback_summary = rlms_context.get("feedback_summary", "")

        # 2. Research Ops — interview planning and gap analysis
        research_agent = ResearchOps(self._llm)
        research_result = research_agent.run(
            product_name=product_name,
            context_summary=global_summary,
            existing_feedback=feedback,
            stakeholder_roles=stakeholder_roles,
        )
        interview_plan = research_result.output
        steps.append(research_result.to_dict())

        # 3. Design Reasoner — analyze designs if provided
        design_analysis = None
        if design_input and (design_input.descriptions or design_input.image_base64):
            design_agent = DesignReasoner(self._llm)
            images = [
                ImageInput.from_base64(img["data"], img.get("media_type", "image/png"))
                for img in design_input.image_base64
            ] if design_input.image_base64 else []
            design_result = design_agent.run(
                product_name=product_name,
                context_summary=global_summary,
                design_descriptions=design_input.descriptions,
                design_images=images,
            )
            design_analysis = design_result.output
            steps.append(design_result.to_dict())

        # 4. PRD Writer — generate the PRD with reasoning
        prd_agent = PRDWriter(self._llm)
        prd_result = prd_agent.run(
            product_name=product_name,
            context_summary=global_summary,
            feedback_summary=feedback_summary,
            research_insights=interview_plan,
            design_analysis=design_analysis,
        )
        prd = prd_result.output.get("prd", {})
        steps.append(prd_result.to_dict())

        # 5. Delivery Planner — convert PRD to tickets
        delivery_agent = DeliveryPlanner(self._llm)
        delivery_result = delivery_agent.run(
            product_name=product_name,
            prd=prd,
            target_integrations=target_integrations,
        )
        tickets = delivery_result.output.get("tickets", [])
        distribution = delivery_result.output.get("distribution", [])
        steps.append(delivery_result.to_dict())

        orchestration = {
            "strategy": "llm-powered staged planner",
            "started_at": started_at,
            "completed_at": self._now_iso(),
            "steps": [
                {"agent": s["agent"], "status": s["status"], "output": list(s.get("output", {}).keys()) if isinstance(s.get("output"), dict) else s.get("output", "")}
                for s in steps
            ],
            "total_token_usage": self._merge_token_usage(steps),
        }

        return {
            "rlms_context": rlms_context,
            "interview_plan": interview_plan,
            "prd": prd,
            "design_analysis": design_analysis,
            "tickets": tickets,
            "distribution": distribution,
            "orchestration": orchestration,
        }

    def _execute_fallback_pipeline(
        self,
        product_name: str,
        documents: list[str],
        feedback: list[str],
        target_integrations: list[str],
        steps: list[dict[str, Any]],
        started_at: str,
    ) -> dict[str, Any]:
        """Deterministic fallback when no LLM is configured (tests, CI)."""
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
            "design_analysis": None,
            "tickets": tickets,
            "distribution": distribution,
            "orchestration": orchestration,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _merge_token_usage(self, steps: list[dict[str, Any]]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for step in steps:
            for k, v in step.get("token_usage", {}).items():
                merged[k] = merged.get(k, 0) + v
        return merged

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

    # -- Fallback methods (used when no LLM is available) --

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
            {"agent": "design-reasoner", "goal": "Analyze design mockups and specs for UX quality, accessibility, and PRD alignment."},
            {"agent": "delivery-planner", "goal": "Convert PRD outcomes into tickets and distribute them to tools."},
        ]

    def _public_run(self, run: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in run.items() if not k.startswith("_")}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
