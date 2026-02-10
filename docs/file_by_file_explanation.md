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
Main UI shell and flow:
- top navigation + hero section,
- SSO login form with provider buttons,
- integration cards section with admin connect actions,
- side-by-side login + “what happens next” panels.

### `frontend/src/components/IntegrationCard.tsx`
Presentational card for each integration with status, subtitle, and connect button state.

### `frontend/src/styles.css`
Comprehensive styling for layout, typography, cards, gradient buttons, and responsive breakpoints.

### `frontend/src/api.ts`
Browser API calls to FastAPI endpoints, including provider fetch.

### `frontend/src/types.ts`
Frontend TypeScript types shared across UI and API layer.

### `frontend/src/main.tsx`
React entrypoint and CSS import.

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
