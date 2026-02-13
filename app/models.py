# app/models.py
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

IntegrationName = Literal["jira", "confluence", "slack", "teams"]
AuthMode = Literal["org_app", "user_delegated"]


class ActionRequest(BaseModel):
    action: str = Field(..., description="Example: read_snapshot, create_issue, edit_page")
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
