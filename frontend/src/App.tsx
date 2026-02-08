import { useEffect, useMemo, useState } from "react";
import { connectIntegration, getProviders, login } from "./api";
import { IntegrationCard } from "./components/IntegrationCard";
import type { IdPName, IntegrationName, IntegrationState, SessionContext } from "./types";

const integrations: IntegrationName[] = ["jira", "confluence", "slack", "teams"];

export function App() {
  const [session, setSession] = useState<SessionContext | null>(null);
  const [states, setStates] = useState<IntegrationState[]>([]);
  const [email, setEmail] = useState("admin@example.com");
  const [fullName, setFullName] = useState("Admin User");
  const [isAdmin, setIsAdmin] = useState(true);
  const [idpProvider, setIdpProvider] = useState<IdPName>("okta");
  const [providers, setProviders] = useState<IdPName[]>(["okta", "google", "microsoft", "saml"]);

  useEffect(() => {
    getProviders()
      .then((data) => {
        setProviders(data.providers);
        if (data.providers.length > 0) setIdpProvider(data.providers[0]);
      })
      .catch(() => {
        // Keep local fallback providers.
      });
  }, []);

  const statusMap = useMemo(
    () => Object.fromEntries(states.map((s) => [s.integration, s])),
    [states]
  );

  async function onLogin() {
    const data = await login({ idp_provider: idpProvider, email, full_name: fullName, is_admin: isAdmin });
    setSession(data.session);
    setStates(data.org_integrations);
  }

  async function onConnect(name: IntegrationName) {
    if (!session) return;
    await connectIntegration(session.session_id, session.org_domain, name);
    const data = await login({
      idp_provider: session.idp_provider,
      email: session.user_email,
      full_name: fullName,
      is_admin: session.is_admin
    });
    setStates(data.org_integrations);
  }

  return (
    <main style={{ maxWidth: 700, margin: "24px auto", fontFamily: "Arial, sans-serif" }}>
      <h1>PM Integration Console</h1>
      <p>SSO once, admin connects tools once, team members inherit access.</p>

      {!session ? (
        <section>
          <div>
            <label>SSO Provider: </label>
            <select value={idpProvider} onChange={(e) => setIdpProvider(e.target.value as IdPName)}>
              {providers.map((provider) => (
                <option key={provider} value={provider}>
                  {provider === "microsoft" ? "Microsoft Entra ID" : provider}
                </option>
              ))}
            </select>
          </div>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Full name" />
          <label>
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Admin
          </label>
          <button onClick={onLogin}>Login with SSO</button>
        </section>
      ) : (
        <section>
          <div>
            Logged in as <b>{session.user_email}</b> via <b>{session.idp_provider}</b> ({session.is_admin ? "Admin" : "Member"})
          </div>
          <h3>Org Integrations ({session.org_domain})</h3>
          {integrations.map((name) => (
            <IntegrationCard
              key={name}
              name={name}
              connected={Boolean(statusMap[name]?.connected)}
              canConnect={session.is_admin}
              onConnect={onConnect}
            />
          ))}
          {!session.is_admin && <p>Ask your admin to connect missing integrations.</p>}
        </section>
      )}
    </main>
  );
}
