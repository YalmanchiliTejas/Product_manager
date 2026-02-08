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
