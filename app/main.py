from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from .models import ActionRequest, AdminConnectRequest, SSOLoginRequest
from .services import PlatformService

app = FastAPI(title="PM Integration Backend", version="0.4.0")
service = PlatformService()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/sso/providers")
def sso_providers() -> dict:
    return {"providers": service.supported_identity_providers()}


@app.post("/auth/sso/login")
def sso_login(payload: SSOLoginRequest) -> dict:
    try:
        session = service.sso_login(payload)
        integrations = service.get_org_integrations(session.org_domain)
        needs_admin = not any(item.connected for item in integrations)
        return {
            "session": asdict(session),
            "org_integrations": [asdict(i) for i in integrations],
            "admin_action_required": needs_admin,
            "supported_sso_providers": service.supported_identity_providers(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/org/integrations/admin/connect")
def connect_org_integration(session_id: str, payload: AdminConnectRequest) -> dict:
    try:
        state = service.connect_org_integration(session_id, payload)
        return {"integration": asdict(state), "status": "connected"}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/org/integrations/status/{org_domain}")
def integration_status(org_domain: str) -> dict:
    return {
        "org_domain": org_domain,
        "integrations": [asdict(i) for i in service.get_org_integrations(org_domain)],
    }


@app.post("/actions/authorize")
def authorize_action(payload: ActionRequest) -> dict:
    try:
        return service.authorize_action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/consent/{integration}")
def grant_consent(integration: str, session_id: str) -> dict:
    try:
        service.grant_consent(session_id, integration)
        return {"session_id": session_id, "integration": integration, "consent_granted": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
