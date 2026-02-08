# Step 1: SSO + admin integration connections

This step now contains only the connection flow:

1. User logs in via SSO (Okta, Google Workspace, Microsoft Entra ID, or SAML).
2. Admin connects Jira/Confluence/Slack/Teams once for the org.
3. All users in org can see connected integrations.
4. User delegated consent is checked only for write actions.

Graph work is removed from this step.

## Next

- Persist sessions/integrations in a real database.
- Implement real OAuth/admin-consent flows for each integration.
- Add write actions and background sync workers.
