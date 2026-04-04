export type CompanionConfig = {
  apiBaseUrl?: string;
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
  meta_json?: string;
};

export type CompanionSession = {
  id: number;
  session_key: string;
  device_id?: number | null;
  workspace_id?: number | null;
  agent_session_id?: string;
  status?: string;
  mode?: string;
  current_route?: string;
  current_view?: string;
  active_task?: string;
  summary?: string;
};

export type LiveOperatorSnapshot = {
  active?: boolean;
  mode?: string;
  phase?: string;
  title?: string;
  detail?: string;
  tool?: string;
  summary?: string;
  workspace_id?: number | null;
  workspace_name?: string;
  workspace_path?: string;
  started_at?: string;
  updated_at?: string;
  auto_session_id?: string;
  feed?: Array<Record<string, unknown>>;
};

export type CompanionLiveSnapshot = {
  at?: string;
  operator?: LiveOperatorSnapshot | null;
  focus?: {
    workspace_id?: number | null;
    workspace?: {
      id?: number | null;
      name?: string;
      path?: string;
      git_branch?: string;
    } | null;
    session_id?: number | null;
  } | null;
  session?: CompanionSession | null;
  presence?: CompanionPresence | null;
};

export type ApprovalAction = {
  action_type?: string;
  action_fingerprint?: string;
  session_id?: string;
  summary?: string;
  scope_options?: string[];
  persist_allowed?: boolean;
};

export type ApprovalRequired = {
  kind?: string;
  message?: string;
  action_type?: string;
  action_fingerprint?: string;
  approval_action?: ApprovalAction;
  resume_task?: string;
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
  voice_mode?: string;
  approval_required?: ApprovalRequired | null;
  tool_events?: Array<Record<string, unknown>>;
  presence?: CompanionPresence | null;
  live?: CompanionLiveSnapshot | null;
};

export type LocalVoiceStatus = {
  available?: boolean;
  preferred_mode?: string;
  transcription_available?: boolean;
  synthesis_available?: boolean;
  ffmpeg_available?: boolean;
  faster_whisper_available?: boolean;
  whisper_available?: boolean;
  piper_available?: boolean;
  stt_model?: string;
  language?: string;
  detail?: string;
  state?: Record<string, unknown>;
};

export type RiskTier = 'observe' | 'act' | 'destructive' | 'break_glass';

export type TrustedDeviceState = {
  device_id: number;
  trust_state?: string;
  max_risk_tier?: RiskTier | string;
  biometric_enabled?: number | boolean;
  last_biometric_at?: string | null;
  elevated_until?: string | null;
  meta_json?: string;
};

export type MobileElevationSession = {
  id: number;
  device_id: number;
  elevation_key: string;
  risk_tier?: RiskTier | string;
  status?: string;
  verified_via?: string;
  verified_at?: string | null;
  expires_at?: string | null;
};

export type TrustSnapshot = {
  device_id: number;
  trusted: TrustedDeviceState;
  elevation: {
    active: boolean;
    highest_risk_tier?: RiskTier | string;
    sessions: MobileElevationSession[];
  };
  effective_max_risk_tier?: RiskTier | string;
  challenge_required?: boolean;
};

export type VaultStatus = {
  is_setup: boolean;
  is_unlocked: boolean;
  ttl_remaining: number;
  dev_bypass?: boolean;
  biometric_reunlock_enabled?: boolean;
  biometric_reunlock_available?: boolean;
  biometric_reunlock_expires_at?: string | null;
  biometric_reunlock_last_used_at?: string | null;
};

export type VaultProviderKeys = {
  unlocked: boolean;
  resolved: Record<string, boolean>;
  dev_bypass?: boolean;
};

export type PushSubscriptionRequest = {
  device_id: number;
  endpoint: string;
  provider?: string;
  auth?: Record<string, unknown>;
  p256dh?: string;
  expiration_at?: string | null;
};
