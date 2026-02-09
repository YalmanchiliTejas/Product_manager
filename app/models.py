from __future__ import annotations

from datetime import datetime
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


# ---------- document models ----------

class MongoBase(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
    )


class TenantDoc(MongoBase):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    domain: str
    name: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class UserDoc(MongoBase):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    tenant_id: PyObjectId
    email: str
    full_name: str = ""
    is_admin: bool = False

    idp_issuer: str = ""
    idp_sub: str = ""

    created_at: datetime = Field(default_factory=utcnow)


class SessionDoc(MongoBase):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    session_id: str
    tenant_id: PyObjectId
    user_id: PyObjectId

    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)


class IntegrationDoc(MongoBase):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    tenant_id: PyObjectId
    provider: IntegrationName
    auth_mode: AuthMode

    # null for org_app, set for user_delegated
    user_id: Optional[PyObjectId] = None

    # Slack workspace id, Atlassian cloud_id, etc.
    external_tenant_id: str = ""

    scopes: str = ""
    token_type: str = "Bearer"

    access_token_enc: str = ""
    refresh_token_enc: str = ""
    expires_at: Optional[datetime] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # convenience (not stored)
    def scopes_as_list(self) -> List[str]:
        return scopes_list(self.scopes)


class WebhookRouteDoc(MongoBase):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    provider: str  # "slack" | "teams" | "jira" etc.
    route_key: str  # Slack team_id, Graph clientState, Atlassian cloud_id
    tenant_id: PyObjectId

    created_at: datetime = Field(default_factory=utcnow)


# ---------- API payloads ----------

class ActionRequest(BaseModel):
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
