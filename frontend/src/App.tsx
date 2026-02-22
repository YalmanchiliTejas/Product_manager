import { useEffect, useMemo, useState } from "react";
import { connectIntegration, getProviders, login } from "./api";
import { IntegrationCard } from "./components/IntegrationCard";
import { WorkflowPanel } from "./components/WorkflowPanel";
import { PRDView } from "./components/PRDView";
import type { IdPName, IntegrationName, IntegrationState, SessionContext, WorkflowRun } from "./types";

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
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null);
  const [tab, setTab] = useState<"setup" | "workflow" | "results">("setup");

  useEffect(() => {
    getProviders()
      .then((data) => {
        setProviders(data.providers);
        if (data.providers.length > 0) setIdpProvider(data.providers[0]);
      })
      .catch(() => {});
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
          <a href="#" className={tab === "setup" ? "nav-active" : ""} onClick={() => setTab("setup")}>Setup</a>
          <a href="#" className={tab === "workflow" ? "nav-active" : ""} onClick={() => session && setTab("workflow")}>Workflow</a>
          {activeRun && (
            <a href="#" className={tab === "results" ? "nav-active" : ""} onClick={() => setTab("results")}>Results</a>
          )}
        </nav>
        {session && (
          <div className="session-pill compact">
            {session.user_email} ({session.org_domain})
          </div>
        )}
      </header>

      {tab === "setup" && (
        <>
          <section className="hero">
            <p className="kicker">AI-Powered Product Management</p>
            <h1>
              From context to <span>shipped PRDs</span>
            </h1>
            <p className="hero-copy">
              Feed in Slack threads, Confluence pages, interview notes, and design mockups.
              AI agents reason through your product decisions and generate structured PRDs with tickets.
            </p>
          </section>

          <section className="login-shell" id="login">
            <article className="login-card">
              <h2>Sign in to continue</h2>
              <p>Use your company identity provider.</p>

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
              <h3>How it works</h3>
              <ol>
                <li>Sign in and connect your tools (Jira, Confluence, Slack, Teams).</li>
                <li>Provide context: documents, Slack threads, Confluence pages, feedback.</li>
                <li>Upload design mockups or describe wireframes.</li>
                <li>AI agents reason through and generate a PRD with tickets.</li>
                <li>Review, add more feedback, and iterate.</li>
              </ol>
              {session ? (
                <div className="session-pill">
                  Logged in as <strong>{session.user_email}</strong> ({session.idp_provider})
                  <button className="btn btn-gradient" style={{ marginLeft: 12 }} onClick={() => setTab("workflow")}>
                    Go to Workflow
                  </button>
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
                  Org: <strong>{session.org_domain}</strong> | Role: <strong>{session.is_admin ? "Admin" : "Member"}</strong>
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
              <div className="notice">Ask your admin to connect missing tools.</div>
            )}
          </section>
        </>
      )}

      {tab === "workflow" && session && (
        <WorkflowPanel
          session={session}
          onRunComplete={(run) => {
            setActiveRun(run);
            setTab("results");
          }}
        />
      )}

      {tab === "results" && activeRun && (
        <PRDView run={activeRun} onUpdate={setActiveRun} />
      )}
    </div>
  );
}
