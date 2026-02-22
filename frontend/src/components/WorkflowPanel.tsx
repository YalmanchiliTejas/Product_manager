import { useState } from "react";
import { startWorkflow } from "../api";
import type { SessionContext, WorkflowRun, DesignInput } from "../types";

export function WorkflowPanel(props: {
  session: SessionContext;
  onRunComplete: (run: WorkflowRun) => void;
}) {
  const [productName, setProductName] = useState("");
  const [documents, setDocuments] = useState("");
  const [interviewNotes, setInterviewNotes] = useState("");
  const [designDescriptions, setDesignDescriptions] = useState("");
  const [designImages, setDesignImages] = useState<{ data: string; media_type: string }[]>([]);
  const [slackQueries, setSlackQueries] = useState("");
  const [confluenceQueries, setConfluenceQueries] = useState("");
  const [confluencePageIds, setConfluencePageIds] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        const base64 = result.split(",")[1];
        const mediaType = file.type || "image/png";
        setDesignImages((prev) => [...prev, { data: base64, media_type: mediaType }]);
      };
      reader.readAsDataURL(file);
    });
  }

  async function onStart() {
    if (!productName.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const docs = documents
        .split("\n---\n")
        .map((d) => d.trim())
        .filter(Boolean);
      const notes = interviewNotes
        .split("\n")
        .map((n) => n.trim())
        .filter(Boolean);
      const designs = designDescriptions
        .split("\n---\n")
        .map((d) => d.trim())
        .filter(Boolean);

      const designInput: DesignInput | undefined =
        designs.length > 0 || designImages.length > 0
          ? { descriptions: designs, image_base64: designImages }
          : undefined;

      const slackSearchQueries = slackQueries.split("\n").map(s => s.trim()).filter(Boolean);
      const confSearchQueries = confluenceQueries.split("\n").map(s => s.trim()).filter(Boolean);
      const confPageIdList = confluencePageIds.split(",").map(s => s.trim()).filter(Boolean);

      const run = await startWorkflow({
        session_id: props.session.session_id,
        product_name: productName,
        documents: docs,
        interview_notes: notes,
        target_integrations: ["jira", "slack"],
        design_input: designInput,
        slack_sources: slackSearchQueries.length > 0
          ? { channel_ids: [], thread_refs: [], search_queries: slackSearchQueries }
          : undefined,
        confluence_sources: confSearchQueries.length > 0 || confPageIdList.length > 0
          ? { page_ids: confPageIdList, search_queries: confSearchQueries, space_keys: [], labels: [] }
          : undefined,
      });
      props.onRunComplete(run);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="workflow-panel">
      <div className="section-header">
        <p className="kicker">AI Agent Pipeline</p>
        <h2>Start a product workflow</h2>
        <p>Provide context, feedback, and designs. The AI agents will generate a PRD with reasoned decisions.</p>
      </div>

      <div className="workflow-grid">
        <div className="workflow-inputs">
          <div className="input-group">
            <label className="input-label">Product Name *</label>
            <input
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="e.g. Onboarding Copilot"
            />
          </div>

          <div className="input-group">
            <label className="input-label">Source Documents</label>
            <p className="input-hint">Paste documents, call transcripts, research notes. Separate multiple docs with ---</p>
            <textarea
              value={documents}
              onChange={(e) => setDocuments(e.target.value)}
              rows={5}
              placeholder="Customer call transcript discussing onboarding pain points..."
            />
          </div>

          <div className="input-group">
            <label className="input-label">Interview / Feedback Notes</label>
            <p className="input-hint">One note per line</p>
            <textarea
              value={interviewNotes}
              onChange={(e) => setInterviewNotes(e.target.value)}
              rows={3}
              placeholder="PMs spend too much time rewriting requirements from scattered notes."
            />
          </div>

          <div className="input-group">
            <label className="input-label">Design Descriptions</label>
            <p className="input-hint">Describe wireframes, user flows, or UX specs. Separate with ---</p>
            <textarea
              value={designDescriptions}
              onChange={(e) => setDesignDescriptions(e.target.value)}
              rows={3}
              placeholder="Main dashboard shows a kanban board with columns for Discovery, In Progress, Review..."
            />
          </div>

          <div className="input-group">
            <label className="input-label">Design Mockups (Images)</label>
            <input type="file" accept="image/*" multiple onChange={handleImageUpload} />
            {designImages.length > 0 && (
              <p className="input-hint">{designImages.length} image(s) attached</p>
            )}
          </div>

          <div className="source-integrations">
            <h4>Pull from Integrations</h4>
            <div className="source-grid">
              <div className="input-group">
                <label className="input-label">Slack Search Queries</label>
                <textarea
                  value={slackQueries}
                  onChange={(e) => setSlackQueries(e.target.value)}
                  rows={2}
                  placeholder="onboarding feedback&#10;product requirements discussion"
                />
              </div>
              <div className="input-group">
                <label className="input-label">Confluence Search / Page IDs</label>
                <textarea
                  value={confluenceQueries}
                  onChange={(e) => setConfluenceQueries(e.target.value)}
                  rows={2}
                  placeholder="product requirements document"
                />
                <input
                  value={confluencePageIds}
                  onChange={(e) => setConfluencePageIds(e.target.value)}
                  placeholder="Comma-separated page IDs (optional)"
                />
              </div>
            </div>
          </div>

          {error && <div className="notice" style={{ borderColor: "#e74c3c", color: "#c0392b" }}>{error}</div>}

          <button className="btn btn-gradient btn-lg" onClick={onStart} disabled={loading || !productName.trim()}>
            {loading ? "Running agents..." : "Run AI Agent Pipeline"}
          </button>
        </div>

        <div className="workflow-info">
          <h3>Agent Pipeline</h3>
          <ol>
            <li><strong>Context Architect</strong> — Ingests documents with recursive LLM summarization (RLMS)</li>
            <li><strong>Research Ops</strong> — Generates targeted interview questions, analyzes feedback gaps</li>
            <li><strong>Design Reasoner</strong> — Analyzes mockups and specs for UX quality and PRD alignment</li>
            <li><strong>PRD Writer</strong> — Reasons through trade-offs, then generates a structured PRD</li>
            <li><strong>Delivery Planner</strong> — Converts PRD into tickets with dependencies and execution plan</li>
          </ol>
        </div>
      </div>
    </section>
  );
}
