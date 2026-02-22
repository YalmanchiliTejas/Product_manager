import { useState } from "react";
import { ingestFeedback } from "../api";
import type { WorkflowRun } from "../types";

function Section(props: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(props.defaultOpen ?? true);
  return (
    <div className="prd-section">
      <button className="prd-section-toggle" onClick={() => setOpen(!open)}>
        <span>{open ? "\u25BC" : "\u25B6"}</span> {props.title}
      </button>
      {open && <div className="prd-section-body">{props.children}</div>}
    </div>
  );
}

export function PRDView(props: { run: WorkflowRun; onUpdate: (run: WorkflowRun) => void }) {
  const { run } = props;
  const prd = run.prd as Record<string, unknown>;
  const [newFeedback, setNewFeedback] = useState("");
  const [ingesting, setIngesting] = useState(false);

  async function onIngest() {
    const notes = newFeedback.split("\n").map(n => n.trim()).filter(Boolean);
    if (notes.length === 0) return;
    setIngesting(true);
    try {
      const result = await ingestFeedback(run.run_id, notes);
      props.onUpdate(result.run);
      setNewFeedback("");
    } finally {
      setIngesting(false);
    }
  }

  return (
    <section className="prd-view">
      <div className="section-header">
        <p className="kicker">Generated Output</p>
        <h2>{(prd.title as string) || `PRD: ${run.product_name}`}</h2>
      </div>

      {/* Orchestration trace */}
      <Section title="Agent Pipeline Trace">
        <div className="trace-steps">
          {run.orchestration.steps.map((step, i) => (
            <div key={i} className={`trace-step ${step.status}`}>
              <span className="trace-dot" />
              <span className="trace-agent">{step.agent}</span>
              <span className="trace-status">{step.status}</span>
            </div>
          ))}
        </div>
        <p className="input-hint">
          Strategy: {run.orchestration.strategy} | Completed: {run.orchestration.completed_at}
        </p>
      </Section>

      {/* PRD Content */}
      <Section title="Problem Statement">
        <p>{prd.problem_statement as string}</p>
      </Section>

      {Array.isArray(prd.goals) && (
        <Section title="Goals">
          <ul>{(prd.goals as string[]).map((g, i) => <li key={i}>{g}</li>)}</ul>
        </Section>
      )}

      {Array.isArray(prd.non_goals) && (
        <Section title="Non-Goals">
          <ul>{(prd.non_goals as string[]).map((g, i) => <li key={i}>{g}</li>)}</ul>
        </Section>
      )}

      {Array.isArray(prd.user_stories) && (
        <Section title="User Stories" defaultOpen={false}>
          {(prd.user_stories as Record<string, unknown>[]).map((story, i) => (
            <div key={i} className="user-story">
              <strong>{story.persona as string}</strong>: {story.story as string}
              {Array.isArray(story.acceptance_criteria) && (
                <ul>{(story.acceptance_criteria as string[]).map((c, j) => <li key={j}>{c}</li>)}</ul>
              )}
            </div>
          ))}
        </Section>
      )}

      {Array.isArray(prd.requirements) && (
        <Section title="Requirements">
          <table className="prd-table">
            <thead>
              <tr><th>ID</th><th>Description</th><th>Priority</th><th>Rationale</th></tr>
            </thead>
            <tbody>
              {(prd.requirements as Record<string, string>[]).map((req, i) => (
                <tr key={i}>
                  <td>{req.id}</td>
                  <td>{req.description}</td>
                  <td><span className={`priority-badge ${req.priority?.toLowerCase()}`}>{req.priority}</span></td>
                  <td>{req.rationale}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {Array.isArray(prd.success_metrics) && (
        <Section title="Success Metrics" defaultOpen={false}>
          <table className="prd-table">
            <thead><tr><th>Metric</th><th>Target</th><th>Measurement</th></tr></thead>
            <tbody>
              {(prd.success_metrics as Record<string, string>[]).map((m, i) => (
                <tr key={i}><td>{m.metric}</td><td>{m.target}</td><td>{m.measurement}</td></tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {Array.isArray(prd.risks) && (
        <Section title="Risks" defaultOpen={false}>
          <table className="prd-table">
            <thead><tr><th>Risk</th><th>Impact</th><th>Mitigation</th></tr></thead>
            <tbody>
              {(prd.risks as Record<string, string>[]).map((r, i) => (
                <tr key={i}><td>{r.risk}</td><td>{r.impact}</td><td>{r.mitigation}</td></tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {/* Design Analysis */}
      {run.design_analysis && (
        <Section title="Design Analysis" defaultOpen={false}>
          <pre className="json-block">{JSON.stringify(run.design_analysis, null, 2)}</pre>
        </Section>
      )}

      {/* Tickets */}
      <Section title={`Tickets (${run.tickets.length})`}>
        <div className="tickets-list">
          {run.tickets.map((t, i) => (
            <div key={i} className="ticket-card">
              <div className="ticket-head">
                <span className="ticket-id">{t.id as string}</span>
                <span className={`priority-badge ${(t.priority as string)?.toLowerCase()}`}>{t.priority as string}</span>
              </div>
              <strong>{t.title as string}</strong>
              {t.description && <p>{t.description as string}</p>}
              {t.owner_role && <span className="ticket-owner">{t.owner_role as string}</span>}
            </div>
          ))}
        </div>
      </Section>

      {/* Feedback ingest */}
      <Section title="Add More Feedback">
        <p className="input-hint">Add new interview notes or feedback to re-synthesize the PRD.</p>
        <textarea
          value={newFeedback}
          onChange={(e) => setNewFeedback(e.target.value)}
          rows={3}
          placeholder="Enter new feedback, one item per line..."
        />
        <button className="btn btn-gradient" onClick={onIngest} disabled={ingesting || !newFeedback.trim()}>
          {ingesting ? "Re-synthesizing..." : "Ingest & Re-synthesize"}
        </button>
      </Section>
    </section>
  );
}
