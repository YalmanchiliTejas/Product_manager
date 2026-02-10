import { useEffect, useMemo, useState } from "react";
import { connectIntegration, getProviders, login } from "./api";
import { IntegrationCard } from "./components/IntegrationCard";
import type { IdPName, IntegrationName, IntegrationState, SessionContext } from "./types";

const integrations: IntegrationName[] = ["jira", "confluence", "slack", "teams"];

const providerLabel: Record<IdPName, string> = {
  okta: "Okta",
  google: "Google Workspace",
  microsoft: "Microsoft Entra ID",
  saml: "SAML SSO"
};

const providerIcon: Record<IdPName, string> = {
  okta: "O",
  google: "G",
  microsoft: "M",
  saml: "S"
};

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
        // Keep local fallback providers when API is unavailable.
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
    <div className="page-shell">
      <header className="top-nav">
        <div className="brand">Prod<span>Pilot</span></div>
        <nav>
          <a href="#login">Login</a>
          <a href="#integrations">Integrations</a>
          <a href="#how">How it works</a>
        </nav>
        <button className="btn btn-primary">Book Demo</button>
      </header>

      <section className="hero">
        <p className="kicker">SSO + Integrations Platform</p>
        <h1>
          Connect your workspace in <span>one clean flow</span>
        </h1>
        <p className="hero-copy">
          Pick your identity provider, sign in once, and let admins connect Jira, Confluence, Slack, and Teams for everyone.
        </p>
      </section>

      <section className="login-shell" id="login">
        <article className="login-card">
          <h2>Sign in to continue</h2>
          <p>Use your company identity provider. No dropdown hell — just click your provider.</p>

          <div className="provider-grid">
            {providers.map((provider) => (
              <button
                key={provider}
                className={`provider-btn ${idpProvider === provider ? "active" : ""}`}
                onClick={() => setIdpProvider(provider)}
              >
                <span className="provider-icon">{providerIcon[provider]}</span>
                <span>{providerLabel[provider]}</span>
              </button>
            ))}
          </div>

          <div className="form-grid">
            <label>
              Work email
              <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
            </label>
            <label>
              Full name
              <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Casey Product" />
            </label>
          </div>

          <label className="checkbox-row">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
            I am an org admin
          </label>

          <button className="btn btn-gradient" onClick={onLogin}>
            Continue with {providerLabel[idpProvider]}
          </button>
        </article>

        <article className="preview-card" id="how">
          <h3>What happens next</h3>
          <ol>
            <li>SSO creates your session.</li>
            <li>Admin connects Jira/Confluence/Slack/Teams once.</li>
            <li>Everyone in the org inherits read access.</li>
            <li>User consent is asked only for write actions.</li>
          </ol>
          {session ? (
            <div className="session-pill">
              Logged in as <strong>{session.user_email}</strong> ({session.idp_provider})
            </div>
          ) : (
            <div className="session-pill">Not signed in yet.</div>
          )}
        </article>
      </section>

      <section className="integration-section" id="integrations">
        <div className="section-header">
          <p className="kicker">Admin Connect Stack</p>
          <h2>Integration health</h2>
          {session ? (
            <p>
              Org: <strong>{session.org_domain}</strong> • Role: <strong>{session.is_admin ? "Admin" : "Member"}</strong>
            </p>
          ) : (
            <p>Sign in to load integration status.</p>
          )}
        </div>

        <div className="cards-grid">
          {integrations.map((name) => (
            <IntegrationCard
              key={name}
              name={name}
              connected={Boolean(statusMap[name]?.connected)}
              canConnect={Boolean(session?.is_admin)}
              connectedBy={statusMap[name]?.connected_by ?? null}
              onConnect={onConnect}
            />
          ))}
        </div>

        {session && !session.is_admin && (
          <div className="notice">Ask your admin to connect missing tools. Delegated user consent is only needed for write actions.</div>
        )}
      </section>
    </div>
  );
}
