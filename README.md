# Product Manager Platform (FastAPI + React/TypeScript)

This version focuses only on:

- SSO login into your app.
- Multiple SSO providers (Okta, Google Workspace, Microsoft Entra ID, SAML).
- Admin-only connection for Jira, Confluence, Slack, Teams.
- Org-level inherited access for all users.
- Progressive consent check for user-level write actions.

Knowledge-graph generation is intentionally removed for now.

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

## Frontend (React + TypeScript)

```bash
cd frontend
npm install
npm run dev
```

UI provides:

- modern landing-page style shell (hero, integration section, pricing cards)
- SSO login form with provider select (Microsoft/Google/Okta/SAML)
- integration cards (Jira, Confluence, Slack, Teams) with admin connect actions
- member view prompting "Ask your admin"

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
