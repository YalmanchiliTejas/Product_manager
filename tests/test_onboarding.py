import unittest

from app.models import ActionRequest, AdminConnectRequest, SSOLoginRequest
from app.platform_service import PlatformService


class PlatformFlowTests(unittest.TestCase):
    def setUp(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
