import unittest

from app.models import (
    ActionRequest,
    AdminConnectRequest,
    ConfluenceSourceConfig,
    DesignInput,
    SlackSourceConfig,
    SSOLoginRequest,
)
from app.platform_service import PlatformService


class PlatformFlowTests(unittest.TestCase):
    """Tests for SSO, integration management, and consent flows."""

    def setUp(self) -> None:
        # No LLM — uses deterministic fallback pipeline
        self.service = PlatformService()

    def test_admin_connects_org_integrations(self) -> None:
        admin = self.service.sso_login(
            SSOLoginRequest("microsoft", "admin@example.com", "Admin User", True)
        )
        state = self.service.connect_org_integration(
            admin.session_id,
            AdminConnectRequest(org_domain="example.com", integration="jira", scopes=[]),
        )

        self.assertTrue(state.connected)
        self.assertEqual("admin@example.com", state.connected_by)
        self.assertGreater(len(state.scopes), 0)

    def test_non_admin_cannot_connect(self) -> None:
        member = self.service.sso_login(
            SSOLoginRequest("google", "pm@example.com", "PM User", False)
        )
        with self.assertRaises(PermissionError):
            self.service.connect_org_integration(
                member.session_id,
                AdminConnectRequest(org_domain="example.com", integration="slack", scopes=[]),
            )

    def test_progressive_consent_for_write(self) -> None:
        admin = self.service.sso_login(
            SSOLoginRequest("okta", "admin@example.com", "Admin User", True)
        )
        self.service.connect_org_integration(
            admin.session_id,
            AdminConnectRequest(org_domain="example.com", integration="jira", scopes=[]),
        )
        user = self.service.sso_login(
            SSOLoginRequest("okta", "pm@example.com", "PM User", False)
        )

        before = self.service.authorize_action(
            ActionRequest(session_id=user.session_id, integration="jira", action="create issue")
        )
        self.assertTrue(before["consent_required"])

        self.service.grant_consent(user.session_id, "jira")
        after = self.service.authorize_action(
            ActionRequest(session_id=user.session_id, integration="jira", action="create issue")
        )
        self.assertTrue(after["allowed"])
        self.assertFalse(after["consent_required"])

    def test_supported_identity_providers_list(self) -> None:
        providers = self.service.supported_identity_providers()
        self.assertEqual(["okta", "google", "microsoft", "saml"], providers)

    def test_invalid_identity_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.sso_login(
                SSOLoginRequest("github", "admin@example.com", "Admin User", True)
            )


class FallbackPipelineTests(unittest.TestCase):
    """Tests for the multi-agent workflow using the deterministic fallback (no LLM)."""

    def setUp(self) -> None:
        self.service = PlatformService()

    def test_multi_agent_workflow_generates_prd_and_tickets(self) -> None:
        admin = self.service.sso_login(
            SSOLoginRequest("microsoft", "lead@example.com", "Lead PM", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Product Copilot",
            documents=[
                "Customer call transcript discussing onboarding pain points and migration blockers.",
                "Support ticket export shows top 5 complaints around release communication.",
            ],
            interview_notes=[
                "PMs spend too much time rewriting requirements from scattered notes.",
                "Engineering wants cleaner ticket acceptance criteria from PRDs.",
            ],
            target_integrations=["jira", "slack"],
        )

        self.assertIn("run_id", run)
        self.assertIn("prd", run)
        self.assertEqual("PRD: Product Copilot", run["prd"]["title"])
        self.assertGreaterEqual(len(run["tickets"]), 3)
        self.assertEqual(2, run["rlms_context"]["documents_ingested"])
        self.assertIn("agent_plan", run)
        self.assertIn("orchestration", run)
        self.assertEqual("openclaw-style staged planner", run["orchestration"]["strategy"])
        self.assertEqual(4, len(run["orchestration"]["steps"]))
        self.assertTrue(all(step["status"] == "completed" for step in run["orchestration"]["steps"]))
        self.assertNotIn("_source_documents", run)

    def test_ingest_interview_feedback_updates_run(self) -> None:
        admin = self.service.sso_login(
            SSOLoginRequest("okta", "owner@example.com", "Owner", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Roadmap OS",
            documents=["Initial requirements"],
            interview_notes=[],
        )

        updated = self.service.ingest_interview_feedback(
            run["run_id"],
            ["Need weekly executive updates", "Add risk register automation"],
        )

        self.assertEqual(2, updated["rlms_context"]["feedback_items"])
        self.assertIn("risk register", updated["rlms_context"]["global_summary"].lower())
        self.assertEqual(4, len(updated["orchestration"]["steps"]))

    def test_workflow_with_design_input_passthrough(self) -> None:
        """Design input is accepted but not processed in fallback mode."""
        admin = self.service.sso_login(
            SSOLoginRequest("microsoft", "pm@example.com", "PM", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Design Test",
            documents=["Some product context"],
            interview_notes=["User needs better onboarding"],
            design_input=DesignInput(
                descriptions=["Dashboard with kanban board layout"],
                image_base64=[],
            ),
        )

        self.assertIn("prd", run)
        self.assertIn("tickets", run)
        # In fallback mode, design_analysis is None
        self.assertIsNone(run.get("design_analysis"))

    def test_workflow_with_source_configs(self) -> None:
        """Slack/Confluence source configs are accepted without errors."""
        admin = self.service.sso_login(
            SSOLoginRequest("okta", "lead@example.com", "Lead", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Source Test",
            documents=["Base document"],
            interview_notes=[],
            slack_sources=SlackSourceConfig(
                channel_ids=[], thread_refs=[], search_queries=["product feedback"]
            ),
            confluence_sources=ConfluenceSourceConfig(
                page_ids=["12345"], search_queries=[], space_keys=[], labels=[]
            ),
        )

        self.assertIn("prd", run)
        self.assertIn("run_id", run)

    def test_agent_plan_includes_design_reasoner(self) -> None:
        """The agent plan now includes the design-reasoner agent."""
        admin = self.service.sso_login(
            SSOLoginRequest("microsoft", "pm@example.com", "PM", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Agent Plan Test",
            documents=["Context"],
            interview_notes=[],
        )

        agent_names = [a["agent"] for a in run["agent_plan"]]
        self.assertIn("design-reasoner", agent_names)
        self.assertEqual(5, len(run["agent_plan"]))

    def test_empty_feedback_ingest_is_noop(self) -> None:
        admin = self.service.sso_login(
            SSOLoginRequest("okta", "pm@example.com", "PM", True)
        )
        run = self.service.start_multi_agent_workflow(
            session_id=admin.session_id,
            product_name="Noop Test",
            documents=["Doc"],
            interview_notes=["Initial note"],
        )

        # Ingest empty notes — should return existing run unchanged
        updated = self.service.ingest_interview_feedback(run["run_id"], [])
        self.assertEqual(1, updated["rlms_context"]["feedback_items"])

    def test_invalid_session_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.start_multi_agent_workflow(
                session_id="fake-session-id",
                product_name="Should Fail",
                documents=[],
                interview_notes=[],
            )

    def test_unknown_run_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.workflow_run("nonexistent-run-id")

    def test_fetch_source_context_requires_session(self) -> None:
        with self.assertRaises(ValueError):
            self.service.fetch_source_context("bad-session-id")


class LLMAbstractionTests(unittest.TestCase):
    """Tests for the LLM abstraction layer structure."""

    def test_base_classes_importable(self) -> None:
        from app.llm import LLMProvider, LLMResponse, ImageInput
        self.assertTrue(hasattr(LLMProvider, "chat"))
        self.assertTrue(hasattr(LLMProvider, "chat_with_images"))
        self.assertTrue(hasattr(LLMProvider, "complete"))

    def test_image_input_from_base64(self) -> None:
        from app.llm import ImageInput
        import base64

        raw_bytes = b"fake image data"
        b64 = base64.b64encode(raw_bytes).decode()
        img = ImageInput.from_base64(b64, "image/png")
        self.assertEqual(raw_bytes, img.data)
        self.assertEqual("image/png", img.media_type)
        self.assertEqual(b64, img.to_base64())

    def test_factory_rejects_unknown_provider(self) -> None:
        from app.llm import create_provider
        with self.assertRaises(ValueError):
            create_provider(provider="unsupported_provider")


class AgentStructureTests(unittest.TestCase):
    """Tests that agent classes are properly structured (without LLM calls)."""

    def test_all_agents_importable(self) -> None:
        from app.agents import (
            ContextArchitect,
            ResearchOps,
            PRDWriter,
            DesignReasoner,
            DeliveryPlanner,
        )
        self.assertEqual("context-architect", ContextArchitect.name)
        self.assertEqual("research-ops", ResearchOps.name)
        self.assertEqual("prd-writer", PRDWriter.name)
        self.assertEqual("design-reasoner", DesignReasoner.name)
        self.assertEqual("delivery-planner", DeliveryPlanner.name)

    def test_agent_result_to_dict(self) -> None:
        from app.agents import AgentResult
        result = AgentResult(
            agent_name="test-agent",
            status="completed",
            output={"key": "value"},
            reasoning_trace=["step 1"],
            token_usage={"input_tokens": 100},
        )
        d = result.to_dict()
        self.assertEqual("test-agent", d["agent"])
        self.assertEqual("completed", d["status"])
        self.assertEqual({"key": "value"}, d["output"])


class IntegrationClientStructureTests(unittest.TestCase):
    """Tests that integration clients are properly structured."""

    def test_slack_client_importable(self) -> None:
        from app.integrations import SlackClient
        # Can instantiate with empty token (won't make API calls)
        client = SlackClient(token="xoxb-test")
        self.assertIsNotNone(client)
        client.close()

    def test_confluence_client_importable(self) -> None:
        from app.integrations import ConfluenceClient
        client = ConfluenceClient(
            base_url="https://test.atlassian.net",
            email="test@example.com",
            api_token="fake-token",
        )
        self.assertIsNotNone(client)
        client.close()

    def test_confluence_html_to_text(self) -> None:
        from app.integrations.confluence_client import ConfluenceClient
        html = "<h1>Title</h1><p>Some <strong>bold</strong> text</p><br/><ul><li>Item 1</li><li>Item 2</li></ul>"
        text = ConfluenceClient._html_to_text(html)
        self.assertIn("Title", text)
        self.assertIn("Some bold text", text)
        self.assertIn("Item 1", text)

    def test_slack_thread_to_text(self) -> None:
        from app.integrations.slack_client import SlackMessage, SlackThread
        thread = SlackThread(
            channel="general",
            messages=[
                SlackMessage(user="alice", text="Hello world", ts="1234.5678"),
                SlackMessage(user="bob", text="Hi there", ts="1234.5679", reactions=["thumbsup"]),
            ],
        )
        text = thread.to_text()
        self.assertIn("alice", text)
        self.assertIn("Hello world", text)
        self.assertIn("thumbsup", text)


if __name__ == "__main__":
    unittest.main()
