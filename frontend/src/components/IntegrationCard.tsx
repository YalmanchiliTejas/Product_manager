import type { IntegrationName } from "../types";

const integrationSubtitle: Record<IntegrationName, string> = {
  jira: "Projects, epics, issues",
  confluence: "Pages, spaces, docs",
  slack: "Channels and threads",
  teams: "Teams and channels"
};

export function IntegrationCard(props: {
  name: IntegrationName;
  connected: boolean;
  canConnect: boolean;
  connectedBy: string | null;
  onConnect: (name: IntegrationName) => void;
}) {
  return (
    <article className={`integration-card ${props.connected ? "connected" : ""}`}>
      <div className="integration-head">
        <h3>{props.name.toUpperCase()}</h3>
        <span className={`status-dot ${props.connected ? "on" : "off"}`} />
      </div>
      <p>{integrationSubtitle[props.name]}</p>
      <div className="status-line">{props.connected ? `Connected by ${props.connectedBy ?? "admin"}` : "Not connected"}</div>
      {!props.connected && props.canConnect ? (
        <button className="btn btn-gradient" onClick={() => props.onConnect(props.name)}>
          Connect {props.name}
        </button>
      ) : (
        <button className="btn" disabled={!props.connected}>
          {props.connected ? "Connected" : "Admin required"}
        </button>
      )}
    </article>
  );
}
