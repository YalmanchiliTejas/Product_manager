from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Dict, List

from .models import (
    ActionRequest,
    AdminConnectRequest,
    IntegrationState,
    SessionContext,
    SSOLoginRequest,
    SUPPORTED_IDENTITY_PROVIDERS,
)

READONLY_SCOPES = {
    "jira": ["read:jira-work"],
    "confluence": ["read:confluence-content"],
    "slack": ["channels:read", "channels:history"],
    "teams": ["ChannelMessage.Read.All", "Group.Read.All"],
}
WRITE_PREFIXES = ("create", "comment", "edit", "post", "dm")
SUPPORTED_INTEGRATIONS = ["jira", "confluence", "slack", "teams"]


@dataclass
class SessionStore:
    sessions: Dict[str, SessionContext] = field(default_factory=dict)

    def create(self, payload: SSOLoginRequest) -> SessionContext:
        payload.validate()
        provider = payload.idp_provider.lower().strip()
        org_domain = payload.email.split("@", 1)[1].lower()
        raw = f"{provider}:{payload.email.lower()}".encode()
        session_id = sha256(raw).hexdigest()[:20]
        session = SessionContext(
            session_id=session_id,
            user_email=payload.email.lower(),
            org_domain=org_domain,
            is_admin=payload.is_admin,
            idp_provider=provider,
        )
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> SessionContext:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError("session not found")
        return session


@dataclass
class IntegrationStore:
    by_org: Dict[str, Dict[str, IntegrationState]] = field(default_factory=dict)

    def connect(self, org_domain: str, integration: str, scopes: List[str], connected_by: str) -> IntegrationState:
        org_map = self.by_org.setdefault(org_domain, {})
        state = IntegrationState(
            integration=integration, connected=True, scopes=scopes, connected_by=connected_by
        )
        org_map[integration] = state
        return state

    def list_for_org(self, org_domain: str) -> List[IntegrationState]:
        org_map = self.by_org.get(org_domain, {})
        return [
            org_map.get(name, IntegrationState(integration=name, connected=False, scopes=[]))
            for name in SUPPORTED_INTEGRATIONS
        ]


@dataclass
class ConsentStore:
    grants: Dict[str, set[str]] = field(default_factory=dict)

    def has_grant(self, session_id: str, integration: str) -> bool:
        return integration in self.grants.get(session_id, set())

    def grant(self, session_id: str, integration: str) -> None:
        self.grants.setdefault(session_id, set()).add(integration)


@dataclass
class PlatformService:
    sessions: SessionStore = field(default_factory=SessionStore)
    integrations: IntegrationStore = field(default_factory=IntegrationStore)
    consents: ConsentStore = field(default_factory=ConsentStore)

    def supported_identity_providers(self) -> List[str]:
        return SUPPORTED_IDENTITY_PROVIDERS

    def sso_login(self, payload: SSOLoginRequest) -> SessionContext:
        return self.sessions.create(payload)

    def connect_org_integration(self, session_id: str, payload: AdminConnectRequest) -> IntegrationState:
        session = self.sessions.get(session_id)
        if not session.is_admin:
            raise PermissionError("only admins can connect integrations")
        if session.org_domain != payload.org_domain:
            raise PermissionError("admin can only connect integrations for own org")
        scopes = payload.scopes or READONLY_SCOPES[payload.integration]
        return self.integrations.connect(
            org_domain=payload.org_domain,
            integration=payload.integration,
            scopes=scopes,
            connected_by=session.user_email,
        )

    def get_org_integrations(self, org_domain: str) -> List[IntegrationState]:
        return self.integrations.list_for_org(org_domain)

    def authorize_action(self, payload: ActionRequest) -> dict:
        session = self.sessions.get(payload.session_id)
        org_state = {i.integration: i for i in self.get_org_integrations(session.org_domain)}
        state = org_state[payload.integration]
        if not state.connected:
            return {"allowed": False, "reason": "integration not connected", "consent_required": False}

        if not payload.action.lower().startswith(WRITE_PREFIXES):
            return {"allowed": True, "mode": "org_app", "consent_required": False}

        if self.consents.has_grant(session.session_id, payload.integration):
            return {"allowed": True, "mode": "user_delegated", "consent_required": False}

        return {
            "allowed": False,
            "mode": "user_delegated",
            "consent_required": True,
            "consent_url": f"/consent/{payload.integration}?session_id={session.session_id}",
        }

    def grant_consent(self, session_id: str, integration: str) -> None:
        self.sessions.get(session_id)
        self.consents.grant(session_id, integration)
