# File-by-file explanation

## Backend

### `app/models.py`
Defines all request/response dataclasses:
- SSO login payload and validation.
- Supported SSO providers (`okta`, `google`, `microsoft`, `saml`).
- Session context including selected identity provider.
- Admin integration connect payload.
- Integration connection state.
- Action authorization payload.

### `app/services.py`
Holds business logic:
- Session store for SSO sessions.
- Integration store for org-level Jira/Confluence/Slack/Teams connect status.
- Consent store for delegated user consent.
- Platform service methods for provider listing, login, admin connect, status retrieval, and authorization checks.

### `app/main.py`
FastAPI routes exposing the service layer:
- `GET /auth/sso/providers`
- `POST /auth/sso/login`
- `POST /org/integrations/admin/connect`
- `GET /org/integrations/status/{org_domain}`
- `POST /actions/authorize`
- `POST /consent/{integration}`

### `app/knowledge_graph.py`
Disabled placeholder for now. Graph logic removed in this iteration.

## Frontend

### `frontend/src/App.tsx`
Main UI for:
- SSO login with provider dropdown.
- listing integrations,
- admin connect buttons,
- member "ask your admin" UX.

### `frontend/src/components/IntegrationCard.tsx`
Small presentational card for each integration.

### `frontend/src/api.ts`
Browser API calls to FastAPI endpoints, including provider fetch.

### `frontend/src/types.ts`
Frontend TypeScript types shared across UI and API layer.

### `frontend/src/main.tsx`
React entrypoint.

### `frontend/package.json`, `frontend/tsconfig.json`, `frontend/index.html`
Vite + TypeScript app configuration/bootstrap.

## Tests

### `tests/test_onboarding.py`
Unit tests for backend service behavior:
- admin connect,
- non-admin restriction,
- progressive consent flow,
- supported provider list,
- invalid provider rejection.
