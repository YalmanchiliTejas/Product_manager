import type { IdPName, IntegrationName, IntegrationState, SessionContext } from "./types";

const API = "http://localhost:8000";

export async function getProviders(): Promise<{ providers: IdPName[] }> {
  const res = await fetch(`${API}/auth/sso/providers`);
  if (!res.ok) throw new Error("Failed to fetch providers");
  return res.json();
}

export async function login(payload: {
  idp_provider: IdPName;
  email: string;
  full_name: string;
  is_admin: boolean;
}): Promise<{
  session: SessionContext;
  org_integrations: IntegrationState[];
  admin_action_required: boolean;
  supported_sso_providers: IdPName[];
}> {
  const res = await fetch(`${API}/auth/sso/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error("Login failed");
  return res.json();
}

export async function connectIntegration(sessionId: string, orgDomain: string, integration: IntegrationName) {
  const res = await fetch(`${API}/org/integrations/admin/connect?session_id=${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ org_domain: orgDomain, integration, scopes: [] })
  });
  if (!res.ok) throw new Error("Connect failed");
  return res.json();
}
