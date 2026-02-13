# Step 1: SSO + admin integration connections (+ multi-agent kickoff)

This step contains:

1. User logs in via SSO (Okta, Google Workspace, Microsoft Entra ID, or SAML).
2. Admin connects Jira/Confluence/Slack/Teams once for the org.
3. All users in org can see connected integrations.
4. User delegated consent is checked only for write actions.
5. Multi-agent workflow can be started to ingest docs/feedback and generate PRDs/tickets.

Graph-specific work remains out of scope in this step.

## Next

- Persist multi-agent workflow runs in a real database.
- Implement real OAuth/admin-consent flows for each integration.
- Add asynchronous workers for interview outreach and ticket sync.
- Add evaluator dashboards and optional fine-tune pipelines.
