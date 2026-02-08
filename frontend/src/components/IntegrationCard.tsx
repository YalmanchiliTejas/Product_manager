import type { IntegrationName } from "../types";

export function IntegrationCard(props: {
  name: IntegrationName;
  connected: boolean;
  canConnect: boolean;
  onConnect: (name: IntegrationName) => void;
}) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12, marginBottom: 8 }}>
      <strong>{props.name}</strong>
      <div>Status: {props.connected ? "Connected" : "Not connected"}</div>
      {!props.connected && props.canConnect && (
        <button onClick={() => props.onConnect(props.name)}>Connect</button>
      )}
    </div>
  );
}
