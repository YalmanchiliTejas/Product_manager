from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from pydantic import BaseModel, Field, ConfigDict


# ---------- Mongo helpers ----------

class PyObjectId(ObjectId):
    """Lets Pydantic accept/emit Mongo ObjectId cleanly."""
    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema.update(type="string")
        return schema

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        import pydantic_core
        return pydantic_core.core_schema.no_info_plain_validator_function(cls.validate)

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str) and ObjectId.is_valid(v):
            return ObjectId(v)
        raise ValueError("Invalid ObjectId")


def utcnow() -> datetime:
    return datetime.utcnow()


def scopes_list(scope_str: str) -> List[str]:
    if not scope_str:
        return []
    return [s for s in scope_str.replace(",", " ").split() if s.strip()]


# ---------- enums ----------

IntegrationName = Literal["jira", "confluence", "slack", "teams"]
AuthMode = Literal["org_app", "user_delegated"]


class ActionRequest(BaseModel):
    session_id: str = Field(..., description="Authenticated app session id")
    action: str = Field(..., description='Example: "read_snapshot", "create_issue", "comment_issue"')
    integration: IntegrationName


class AuthorizeResponse(BaseModel):
    allowed: bool
    mode: Optional[AuthMode] = None
    reason: Optional[str] = None
    consent_required: bool = False
    consent_url: Optional[str] = None


class IntegrationStatus(BaseModel):
    provider: IntegrationName
    org_connected: bool
    org_scopes: List[str]
    user_connected: bool
    user_scopes: List[str]


# ---------- Multi-agent workflow models ----------


class SlackSourceConfig(BaseModel):
    """Configuration for pulling context from Slack."""
    channel_ids: List[str] = Field(default_factory=list)
    thread_refs: List[Dict[str, str]] = Field(
        default_factory=list,
        description='List of {"channel": "C...", "thread_ts": "1234.5678"}',
    )
    search_queries: List[str] = Field(default_factory=list)


class ConfluenceSourceConfig(BaseModel):
    """Configuration for pulling context from Confluence."""
    page_ids: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)
    space_keys: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)


class DesignInput(BaseModel):
    """Design input for the design-reasoner agent."""
    descriptions: List[str] = Field(
        default_factory=list,
        description="Text-based design descriptions, user flow specs, wireframe descriptions",
    )
    image_base64: List[Dict[str, str]] = Field(
        default_factory=list,
        description='List of {"data": "base64...", "media_type": "image/png"}',
    )


class MultiAgentStartRequest(BaseModel):
    session_id: str
    product_name: str
    documents: List[str] = Field(default_factory=list, description="Raw text documents to ingest")
    interview_notes: List[str] = Field(default_factory=list)
    target_integrations: List[str] = Field(default_factory=lambda: ["jira", "slack"])
    slack_sources: Optional[SlackSourceConfig] = None
    confluence_sources: Optional[ConfluenceSourceConfig] = None
    design_input: Optional[DesignInput] = None
    stakeholder_roles: List[str] = Field(
        default_factory=lambda: ["End User", "Engineering Lead", "Product Manager", "Designer"],
    )


class InterviewIngestRequest(BaseModel):
    run_id: str
    notes: List[str] = Field(default_factory=list)


class SourceFetchRequest(BaseModel):
    """Request to fetch context from connected integrations."""
    session_id: str
    slack_sources: Optional[SlackSourceConfig] = None
    confluence_sources: Optional[ConfluenceSourceConfig] = None


# ---------- In-memory onboarding models ----------

SUPPORTED_IDENTITY_PROVIDERS = ("okta", "google", "microsoft", "saml")
SUPPORTED_INTEGRATIONS = ("jira", "confluence", "slack", "teams")


@dataclass
class SSOLoginRequest:
    provider: str
    email: str
    full_name: str
    is_admin: bool = False


@dataclass
class SessionContext:
    session_id: str
    email: str
    full_name: str
    is_admin: bool
    org_domain: str
    provider: str


@dataclass
class AdminConnectRequest:
    org_domain: str
    integration: str
    scopes: List[str] = field(default_factory=list)


@dataclass
class IntegrationConnectionState:
    org_domain: str
    integration: str
    connected: bool
    scopes: List[str]
    connected_by: str = ""
