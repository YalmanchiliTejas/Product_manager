import unittest

from app.models import ActionRequest, AdminConnectRequest, SSOLoginRequest
from app.services import PlatformService


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


if __name__ == "__main__":
    unittest.main()
