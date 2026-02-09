# services_mongo.py
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel, ReturnDocument
from pydantic_settings import BaseSettings

WRITE_PREFIXES = ("create", "comment", "edit", "post", "dm")

READ_SCOPES = {
    "jira": ["read:jira-work", "read:jira-user"],
    "confluence": ["read:confluence-content.summary", "read:confluence-content.all"],
    "slack": ["channels:read", "channels:history", "users:read"],
    "teams": ["User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"],
}
WRITE_SCOPES = {
    "jira": ["write:jira-work"],
    "confluence": ["write:confluence-content"],
    "slack": ["chat:write"],
    "teams": ["ChannelMessage.Send"],
}


class Settings(BaseSettings):
    APP_BASE_URL: str = "http://localhost:8000"

    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "pm_platform"

    SESSION_COOKIE_NAME: str = "pm_sid"
    SESSION_TTL_HOURS: int = 24 * 7

    SESSION_MIDDLEWARE_SECRET: str = "change-me"
    FERNET_KEY: str = ""

    # OIDC (SSO)
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = ""

    # Atlassian
    ATLASSIAN_CLIENT_ID: str = ""
    ATLASSIAN_CLIENT_SECRET: str = ""
    ATLASSIAN_REDIRECT_URI: str = ""
    ATLASSIAN_SCOPES: str = ""

    # Slack
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    SLACK_REDIRECT_URI: str = ""
    SLACK_SCOPES: str = ""
    SLACK_SIGNING_SECRET: str = ""

    # Microsoft Graph
    MS_TENANT: str = "common"
    MS_CLIENT_ID: str = ""
    MS_CLIENT_SECRET: str = ""
    MS_REDIRECT_URI: str = ""
    MS_SCOPES: str = ""
    GRAPH_CLIENT_STATE_SECRET: str = "change-me-graph-client-state"

    class Config:
        env_file = ".env"


settings = Settings()
if not settings.FERNET_KEY:
    raise RuntimeError("Missing FERNET_KEY")

fernet = Fernet(settings.FERNET_KEY.encode("utf-8"))

_mongo_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def encrypt_str(value: str) -> str:
    if not value:
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_str(value_enc: str) -> str:
    if not value_enc:
        return ""
    return fernet.decrypt(value_enc.encode("utf-8")).decode("utf-8")


def pkce_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode("ascii")


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def init_mongo() -> AsyncIOMotorDatabase:
    global _mongo_client, _db
    if _db is not None:
        return _db

    _mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
    _db = _mongo_client[settings.MONGODB_DB_NAME]

    await ensure_indexes(_db)
    return _db


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Mongo not initialized. Call init_mongo() at startup.")
    return _db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.tenants.create_indexes([
        IndexModel([("domain", ASCENDING)], unique=True),
    ])
    await db.users.create_indexes([
        IndexModel([("tenant_id", ASCENDING), ("email", ASCENDING)], unique=True),
        IndexModel([("tenant_id", ASCENDING), ("idp_sub", ASCENDING)]),
    ])
    await db.sessions.create_indexes([
        IndexModel([("session_id", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),  # TTL index
    ])
    await db.integrations.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING), ("provider", ASCENDING), ("auth_mode", ASCENDING),
             ("external_tenant_id", ASCENDING), ("user_id", ASCENDING)],
            unique=True
        ),
        IndexModel([("tenant_id", ASCENDING), ("provider", ASCENDING), ("auth_mode", ASCENDING)]),
    ])
    await db.webhook_routes.create_indexes([
        IndexModel([("provider", ASCENDING), ("route_key", ASCENDING)], unique=True),
    ])


# ---------- identity + sessions ----------

async def get_or_create_tenant(db: AsyncIOMotorDatabase, email: str) -> dict:
    domain = email.split("@", 1)[1].lower()
    doc = await db.tenants.find_one({"domain": domain})
    if doc:
        return doc

    doc = {"domain": domain, "name": domain, "created_at": utcnow()}
    await db.tenants.insert_one(doc)
    return await db.tenants.find_one({"domain": domain})


async def upsert_user(db: AsyncIOMotorDatabase, tenant_id: Any, issuer: str, sub: str, email: str, full_name: str) -> dict:
    email_l = email.lower()

    existing = await db.users.find_one({"tenant_id": tenant_id, "email": email_l})
    if existing:
        await db.users.update_one(
            {"_id": existing["_id"]},
            {"$set": {"full_name": full_name or existing.get("full_name", ""),
                      "idp_issuer": issuer, "idp_sub": sub}}
        )
        return await db.users.find_one({"_id": existing["_id"]})

    # bootstrap: first user becomes admin
    count = await db.users.count_documents({"tenant_id": tenant_id})
    is_admin = (count == 0)

    doc = {
        "tenant_id": tenant_id,
        "email": email_l,
        "full_name": full_name or "",
        "is_admin": is_admin,
        "idp_issuer": issuer,
        "idp_sub": sub,
        "created_at": utcnow(),
    }
    await db.users.insert_one(doc)
    return await db.users.find_one({"tenant_id": tenant_id, "email": email_l})


async def create_app_session(db: AsyncIOMotorDatabase, tenant_id: Any, user_id: Any) -> dict:
    sid = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=settings.SESSION_TTL_HOURS)

    await db.sessions.delete_many({"user_id": user_id})  # optional: one active session/user
    doc = {
        "session_id": sid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": utcnow(),
    }
    await db.sessions.insert_one(doc)
    return doc


async def get_current_user(db: AsyncIOMotorDatabase, request) -> dict:
    sid = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not sid:
        raise PermissionError("Not authenticated")

    sess = await db.sessions.find_one({"session_id": sid})
    if not sess or sess["expires_at"] < utcnow():
        raise PermissionError("Session expired")

    user = await db.users.find_one({"_id": sess["user_id"]})
    if not user:
        raise PermissionError("Invalid session user")
    return user


# ---------- integrations ----------

async def save_integration(
    db: AsyncIOMotorDatabase,
    tenant_id: Any,
    provider: str,
    auth_mode: str,
    external_tenant_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: Optional[int],
    scopes: str,
    token_type: str = "Bearer",
    user_id: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict:
    now = utcnow()
    expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None

    query = {
        "tenant_id": tenant_id,
        "provider": provider,
        "auth_mode": auth_mode,
        "external_tenant_id": external_tenant_id,
        "user_id": user_id,
    }
    update = {
        "$set": {
            "scopes": scopes or "",
            "token_type": token_type or "Bearer",
            "access_token_enc": encrypt_str(access_token),
            "refresh_token_enc": encrypt_str(refresh_token),
            "expires_at": expires_at,
            "metadata": metadata or {},
            "updated_at": now,
        },
        "$setOnInsert": {"created_at": now},
    }

    doc = await db.integrations.find_one_and_update(
        query, update, upsert=True, return_document=ReturnDocument.AFTER
    )
    return doc


async def get_integration(db: AsyncIOMotorDatabase, tenant_id: Any, provider: str, auth_mode: str, user_id: Optional[Any]) -> Optional[dict]:
    return await db.integrations.find_one({
        "tenant_id": tenant_id,
        "provider": provider,
        "auth_mode": auth_mode,
        "user_id": user_id,
    })


# ---------- webhook routing ----------

async def upsert_webhook_route(db: AsyncIOMotorDatabase, provider: str, route_key: str, tenant_id: Any) -> None:
    await db.webhook_routes.update_one(
        {"provider": provider, "route_key": route_key},
        {"$set": {"tenant_id": tenant_id, "created_at": utcnow()}},
        upsert=True,
    )


async def tenant_from_webhook(db: AsyncIOMotorDatabase, provider: str, route_key: str):
    row = await db.webhook_routes.find_one({"provider": provider, "route_key": route_key})
    return row["tenant_id"] if row else None


# ---------- scopes + authorize ----------

def action_is_write(action: str) -> bool:
    a = (action or "").lower()
    return a.startswith(WRITE_PREFIXES)


def scopes_list(scope_str: str) -> list[str]:
    if not scope_str:
        return []
    return [s for s in scope_str.replace(",", " ").split() if s.strip()]


def missing_scopes(provider: str, action: str, granted_scopes: list[str]) -> list[str]:
    needed = WRITE_SCOPES.get(provider, []) if action_is_write(action) else READ_SCOPES.get(provider, [])
    granted = set(granted_scopes)
    return [s for s in needed if s not in granted]


# ---------- Slack verification ----------

def verify_slack_signature(request, body: bytes) -> None:
    ts = request.headers.get("X-Slack-Request-Timestamp")
    sig = request.headers.get("X-Slack-Signature")
    if not ts or not sig:
        raise PermissionError("Missing Slack signature headers")

    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - int(ts)) > 300:
        raise PermissionError("Slack request too old")

    base = b"v0:" + ts.encode("utf-8") + b":" + body
    digest = hmac.new(settings.SLACK_SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = "v0=" + digest
    if not hmac.compare_digest(expected, sig):
        raise PermissionError("Invalid Slack signature")


# ---------- Graph clientState routing ----------

def make_graph_client_state(tenant_id: str) -> str:
    msg = str(tenant_id).encode("utf-8")
    mac = hmac.new(settings.GRAPH_CLIENT_STATE_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{tenant_id}:{mac}"


def parse_graph_client_state(client_state: str) -> Optional[str]:
    try:
        tenant_str, mac = client_state.split(":", 1)
        msg = tenant_str.encode("utf-8")
        expected = hmac.new(settings.GRAPH_CLIENT_STATE_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, mac):
            return None
        return tenant_str
    except Exception:
        return None
