# File-by-file explanation

## Backend

### `app/models.py`
Defines:
- Mongo/Pydantic data models and helpers.
- Request payload models used by FastAPI.
- In-memory onboarding dataclasses for SSO sessions/integration state.
- New multi-agent request models for workflow start + interview ingestion.

### `app/services.py`
Holds Mongo utility helpers (indexes, token helpers, scope checks, webhook verification/routing) and database-facing helpers.

### `app/platform_service.py`
Holds the in-memory `PlatformService` used by current routes/tests:
- SSO + admin integration connection + progressive consent.
- Multi-agent orchestration flow with RLMS-style recursive context compression.
- openclaw-style staged planner trace with per-agent step outputs.
- PRD generation, ticket conversion/distribution, interview feedback ingestion, PM ops checklist, and model strategy notes.

### `app/main.py`
FastAPI routes exposing service layer:
- SSO + integration routes.
- Action authorization and consent routes.
- New multi-agent routes:
  - `POST /multi-agent/start`
  - `GET /multi-agent/runs/{run_id}`
  - `POST /multi-agent/interviews/ingest`

### `app/knowledge_graph.py`
Disabled placeholder for now.

## Frontend

### `frontend/src/App.tsx`
Main UI shell and flow with login and integration actions.

### `frontend/src/components/IntegrationCard.tsx`
Card for each integration with status and connect button.

### `frontend/src/styles.css`
Layout and visual styling.

### `frontend/src/api.ts`
Frontend API calls.

### `frontend/src/types.ts`
Shared frontend types.

### `frontend/src/main.tsx`
React entrypoint.

## Tests

### `tests/test_onboarding.py`
Unit tests covering:
- admin connect behavior,
- non-admin restrictions,
- progressive consent,
- provider validation,
- multi-agent run creation,
- interview feedback ingestion updates.
