export type CompanionConfig = {
  accessToken?: string;
  tokenPair?: CompanionTokenPair;
  deviceId?: number | null;
  deviceKey?: string;
  deviceName?: string;
  sessionId?: number | null;
  workspaceId?: number | null;
};

export type CompanionTokenPair = {
  access_token: string;
  refresh_token: string;
  expires_at: string;
};

export type CompanionDevice = {
  id: number;
  device_key: string;
  name: string;
  kind?: string;
  platform?: string;
  model?: string;
  os_version?: string;
  status?: string;
};

export type CompanionAuthSession = {
  id: number;
  device_id: number;
  revoked_at?: string | null;
  expires_at?: string;
};

export type CompanionPairResponse = {
  device: CompanionDevice;
  auth_session: CompanionAuthSession;
  access_token: string;
  refresh_token: string;
  expires_at: string;
};

export type CompanionPresence = {
  device_id: number;
  session_id?: number | null;
  workspace_id?: number | null;
  presence_state?: string;
  voice_state?: string;
  app_state?: string;
  active_route?: string;
  last_seen_at?: string;
};

export type CompanionSession = {
  id: number;
  session_key: string;
  device_id?: number | null;
  workspace_id?: number | null;
  agent_session_id?: string;
  status?: string;
  current_route?: string;
  current_view?: string;
  active_task?: string;
  summary?: string;
};

export type CompanionVoiceTurn = {
  id: number;
  session_id: number;
  workspace_id?: number | null;
  role: 'user' | 'assistant';
  content: string;
  transcript?: string;
  response_text?: string;
  provider?: string;
  voice_mode?: string;
  language?: string;
  audio_format?: string;
  duration_ms?: number;
  tokens_used?: number;
  status?: string;
};

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

export type WorkspaceSummary = {
  workspace?: Record<string, unknown>;
  relationships?: WorkspaceRelationship[];
  attention?: unknown;
};

export type PushSubscriptionRequest = {
  device_id: number;
  endpoint: string;
  provider?: string;
  auth?: Record<string, unknown>;
  p256dh?: string;
  expiration_at?: string | null;
};

export type VoiceTurnRequest = {
  session_id?: number | null;
  workspace_id?: number | null;
  role: 'user' | 'assistant';
  content: string;
  transcript?: string;
  response_text?: string;
  provider?: string;
  voice_mode?: string;
  language?: string;
  audio_format?: string;
};

export type VoiceTurnResponse = {
  session: CompanionSession;
  user_turn: CompanionVoiceTurn;
  assistant_turn: CompanionVoiceTurn;
  response_text: string;
  tokens_used: number;
  backend?: string;
  presence?: CompanionPresence | null;
};
