# Product Manager Platform (FastAPI + React/TypeScript)

This version includes:

- SSO login into your app.
- Multiple SSO providers (Okta, Google Workspace, Microsoft Entra ID, SAML).
- Admin-only connection for Jira, Confluence, Slack, Teams.
- Org-level inherited access for all users.
- Progressive consent check for user-level write actions.
- **New** multi-agent PM workflow orchestration for:
  - large document ingestion with RLMS-style recursive summarization,
  - interview/feedback collection + ingestion,
  - PRD generation,
  - PRD-to-ticket conversion,
  - cross-tool ticket distribution,
  - PM operations checklist generation (roadmaps, releases, risks, stakeholder comms, KPI cadence),
  - openclaw-style staged planner orchestration trace per run (agent-by-agent execution).

## Backend (FastAPI)

Run:

```bash
uvicorn app.main:app --reload
```

Endpoints:

- `GET /auth/sso/providers`
- `POST /auth/sso/login`
- `POST /org/integrations/admin/connect?session_id=...`
- `GET /org/integrations/status/{org_domain}`
- `POST /actions/authorize`
- `POST /consent/{integration}?session_id=...`
- `POST /multi-agent/start`
- `GET /multi-agent/runs/{run_id}`
- `POST /multi-agent/interviews/ingest`

## Multi-agent workflow quickstart

1. Login via `/auth/sso/login` and keep `session.session_id`.
2. POST to `/multi-agent/start` with product name + documents + interview notes.
3. Read generated `prd`, `tickets`, `distribution`, and `pm_ops` from response.
4. Continue enriching feedback with `/multi-agent/interviews/ingest`.

## Can you use DSPy and multiple models (including Cursor)?

Yes.

- **DSPy**: recommended for optimizing prompt modules and evaluator loops (e.g., PRD quality score, ticket clarity score).
- **Multi-model routing**: use cheaper/faster models for extraction/summarization and stronger reasoning models for PRD synthesis/decisioning.
- **Cursor**: can be used as the development/coding client. The orchestration backend can call whichever model providers you configure.
- **Fine-tuning strategy**: start with retrieval + recursive context compression + evaluations; then fine-tune specialized smaller models once you collect high-quality traces.

## Frontend (React + TypeScript)

```bash
cd frontend
npm install
npm run dev
```

UI provides:

- modern landing-page style shell (hero, focused login panel, integration section)
- SSO login form with provider buttons (Microsoft/Google/Okta/SAML)
- integration cards (Jira, Confluence, Slack, Teams) with admin connect actions
- member view prompting "Ask your admin"

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
