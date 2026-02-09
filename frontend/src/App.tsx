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
          <a href="#features">Features</a>
          <a href="#integrations">Integrations</a>
          <a href="#pricing">Pricing</a>
        </nav>
        <button className="btn btn-primary">Join the Waitlist</button>
      </header>

      <section className="hero">
        <p className="kicker">The AI workspace for Product Managers</p>
        <h1>
          Ship products faster with <span>AI superpowers</span>
        </h1>
        <p className="hero-copy">
          One SSO, admin-managed integrations, and progressive consent for actions that act as a user.
        </p>
      </section>

      <section className="auth-panel" id="features">
        <h2>Sign in once with your identity provider</h2>
        <p>Choose your org SSO provider like Atlassian: Microsoft Entra ID, Google Workspace, Okta, or SAML.</p>
        <div className="auth-grid">
          <label>
            SSO Provider
            <select value={idpProvider} onChange={(e) => setIdpProvider(e.target.value as IdPName)}>
              {providers.map((provider) => (
                <option key={provider} value={provider}>
                  {provider === "microsoft" ? "Microsoft Entra ID" : provider}
                </option>
              ))}
            </select>
          </label>
          <label>
            Work email
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </label>
          <label>
            Full name
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Casey Product" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
            I am an org admin
          </label>
        </div>
        <button className="btn btn-gradient" onClick={onLogin}>
          Continue with SSO →
        </button>
      </section>

      <section className="integration-section" id="integrations">
        <div className="section-header">
          <p className="kicker">Admin Connect Stack</p>
          <h2>Connect once, everyone inherits access</h2>
          {session ? (
            <p>
              Logged in as <strong>{session.user_email}</strong> via <strong>{session.idp_provider}</strong> in <strong>{session.org_domain}</strong>.
            </p>
          ) : (
            <p>Login to view and manage integration state.</p>
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
          <div className="notice">Ask your admin to connect missing tools. You only need user consent when doing write actions as yourself.</div>
        )}
      </section>

      <section className="pricing" id="pricing">
        <p className="kicker">Pricing</p>
        <h2>Simple, transparent pricing</h2>
        <div className="pricing-grid">
          <article>
            <h3>Free</h3>
            <p className="price">$0 <span>/ forever</span></p>
            <ul>
              <li>1 workspace</li>
              <li>Basic integration status</li>
              <li>Community support</li>
            </ul>
            <button className="btn">Start Free</button>
          </article>
          <article className="popular">
            <span className="badge">Most Popular</span>
            <h3>Pro</h3>
            <p className="price">$29 <span>/ month</span></p>
            <ul>
              <li>Admin connect stack</li>
              <li>Progressive consent actions</li>
              <li>Priority support</li>
            </ul>
            <button className="btn btn-gradient">Get Started</button>
          </article>
          <article>
            <h3>Enterprise</h3>
            <p className="price">Custom</p>
            <ul>
              <li>Advanced security</li>
              <li>Unlimited users</li>
              <li>Dedicated success manager</li>
            </ul>
            <button className="btn">Contact Sales</button>
          </article>
        </div>
      </section>
    </div>
  );
}
