from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal

IntegrationName = Literal["jira", "confluence", "slack", "teams"]
IdPName = Literal["okta", "google", "microsoft", "saml"]

SUPPORTED_IDENTITY_PROVIDERS: List[IdPName] = ["okta", "google", "microsoft", "saml"]


@dataclass
class SSOLoginRequest:
    idp_provider: str
    email: str
    full_name: str
    is_admin: bool = False

    def validate(self) -> None:
        provider = self.idp_provider.lower().strip()
        if provider not in SUPPORTED_IDENTITY_PROVIDERS:
            raise ValueError("idp_provider must be one of: okta, google, microsoft, saml")
        if "@" not in self.email:
            raise ValueError("email is invalid")
        if not self.full_name.strip():
            raise ValueError("full_name is required")


@dataclass
class SessionContext:
    session_id: str
    user_email: str
    org_domain: str
    is_admin: bool
    idp_provider: IdPName


@dataclass
class AdminConnectRequest:
    org_domain: str
    integration: IntegrationName
    scopes: List[str] = field(default_factory=list)


@dataclass
class IntegrationState:
    integration: IntegrationName
    connected: bool
    scopes: List[str] = field(default_factory=list)
    connected_by: str | None = None


@dataclass
class ActionRequest:
    session_id: str
    integration: IntegrationName
    action: str
