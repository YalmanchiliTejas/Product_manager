export type IntegrationName = "jira" | "confluence" | "slack" | "teams";
export type IdPName = "okta" | "google" | "microsoft" | "saml";

export interface SessionContext {
  session_id: string;
  user_email: string;
  org_domain: string;
  is_admin: boolean;
  idp_provider: IdPName;
}

export interface IntegrationState {
  integration: IntegrationName;
  connected: boolean;
  scopes: string[];
  connected_by: string | null;
}

export interface SlackSourceConfig {
  channel_ids: string[];
  thread_refs: { channel: string; thread_ts: string }[];
  search_queries: string[];
}

export interface ConfluenceSourceConfig {
  page_ids: string[];
  search_queries: string[];
  space_keys: string[];
  labels: string[];
}

export interface DesignInput {
  descriptions: string[];
  image_base64: { data: string; media_type: string }[];
}

export interface WorkflowRequest {
  session_id: string;
  product_name: string;
  documents: string[];
  interview_notes: string[];
  target_integrations: string[];
  slack_sources?: SlackSourceConfig;
  confluence_sources?: ConfluenceSourceConfig;
  design_input?: DesignInput;
  stakeholder_roles?: string[];
}

export interface WorkflowRun {
  run_id: string;
  product_name: string;
  rlms_context: Record<string, unknown>;
  interview_plan: Record<string, unknown>;
  prd: Record<string, unknown>;
  design_analysis?: Record<string, unknown>;
  tickets: Record<string, unknown>[];
  distribution: Record<string, unknown>[];
  orchestration: {
    strategy: string;
    started_at: string;
    completed_at: string;
    steps: { agent: string; status: string }[];
  };
  agent_plan: { agent: string; goal: string }[];
}
