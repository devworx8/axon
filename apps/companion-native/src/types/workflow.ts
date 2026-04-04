import type { RiskTier, VoiceTurnResponse } from './companion-core';

export type AttentionItem = {
  id: number;
  attention_key?: string;
  source?: string;
  item_type?: string;
  title?: string;
  summary?: string;
  detail?: string;
  severity?: string;
  status?: string;
  project_name?: string;
  link_url?: string;
  meta?: Record<string, unknown>;
};

export type WorkspaceRelationship = {
  id: number;
  workspace_id: number;
  external_system: string;
  external_id?: string;
  relationship_type?: string;
  external_name?: string;
  external_url?: string;
  status?: string;
  meta?: Record<string, unknown>;
};

export type ControlCapability = {
  id?: number;
  action_type: string;
  system_name?: string;
  scope?: string;
  risk_tier?: RiskTier | string;
  mobile_direct_allowed?: number | boolean;
  destructive?: number | boolean;
  available?: number | boolean;
  description?: string;
  meta_json?: string;
};

export type RiskChallenge = {
  id: number;
  challenge_key: string;
  device_id: number;
  session_id?: number | null;
  workspace_id?: number | null;
  action_type: string;
  risk_tier?: RiskTier | string;
  title?: string;
  summary?: string;
  status?: string;
  requires_biometric?: number | boolean;
  expires_at?: string | null;
  confirmed_at?: string | null;
  rejected_at?: string | null;
  request_json?: string;
  meta_json?: string;
};

export type ActionReceipt = {
  id: number;
  receipt_key: string;
  device_id?: number | null;
  session_id?: number | null;
  workspace_id?: number | null;
  challenge_id?: number | null;
  action_type: string;
  risk_tier?: RiskTier | string;
  status?: string;
  outcome?: string;
  title?: string;
  summary?: string;
  request_json?: string;
  result_json?: string;
  created_at?: string;
};

export type TypedActionRequest = {
  action_type: string;
  session_id?: number | null;
  workspace_id?: number | null;
  payload?: Record<string, unknown>;
};

export type TypedActionResult = {
  status: string;
  capability?: ControlCapability | null;
  result?: Record<string, unknown> | VoiceTurnResponse | null;
  receipt?: ActionReceipt | null;
  challenge?: RiskChallenge | null;
};

export type McpServerSpec = {
  id: number;
  server_key: string;
  name: string;
  transport?: string;
  endpoint?: string;
  auth_source?: string;
  scope?: string;
  risk_tier?: RiskTier | string;
  enabled?: number | boolean;
  status?: string;
  meta_json?: string;
};

export type McpSessionState = {
  id: number;
  server_id: number;
  session_key: string;
  status?: string;
  detail?: string;
  last_error?: string;
  updated_at?: string;
};
