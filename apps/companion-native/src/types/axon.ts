export type AxonMonitoringState = 'idle' | 'armed' | 'listening' | 'engaged' | 'speaking' | 'degraded';
export type AxonVoiceProvider = 'cloud' | 'local' | 'device' | 'unavailable';

export type AxonLocalVoiceReadiness = {
  available?: boolean;
  transcription_available?: boolean;
  synthesis_available?: boolean;
  preferred_mode?: string;
  detail?: string;
};

export type AxonModeStatus = {
  armed?: boolean;
  available?: boolean;
  foreground_only?: boolean;
  monitoring_state?: AxonMonitoringState | string;
  wake_phrase?: string;
  boot_sound_enabled?: boolean;
  spoken_reply_enabled?: boolean;
  continuous_monitoring_enabled?: boolean;
  voice_provider_preference?: AxonVoiceProvider | string;
  voice_provider?: AxonVoiceProvider | string;
  voice_provider_ready?: boolean;
  voice_provider_detail?: string;
  voice_identity?: string;
  voice_identity_label?: string;
  local_voice_ready?: boolean;
  transcription_ready?: boolean;
  cloud_transcription_available?: boolean;
  local_voice_status?: AxonLocalVoiceReadiness | null;
  summary?: string;
  last_event_type?: string;
  last_event_at?: string;
  last_wake_at?: string;
  last_transcript?: string;
  last_command_text?: string;
  last_command_at?: string;
  last_error?: string;
  degraded_reason?: string;
  active_route?: string;
  app_state?: string;
  updated_at?: string;
};

export type AxonArmRequest = {
  session_id?: number | null;
  workspace_id?: number | null;
  wake_phrase?: string;
  boot_sound_enabled?: boolean;
  spoken_reply_enabled?: boolean;
  continuous_monitoring_enabled?: boolean;
  voice_provider_preference?: AxonVoiceProvider | string;
  voice_identity_preference?: string;
  active_route?: string;
  app_state?: string;
  meta?: Record<string, unknown>;
};

export type AxonDisarmRequest = {
  session_id?: number | null;
  workspace_id?: number | null;
  active_route?: string;
  app_state?: string;
};

export type AxonEventRequest = {
  event_type: string;
  session_id?: number | null;
  workspace_id?: number | null;
  monitoring_state?: string;
  wake_phrase?: string;
  transcript?: string;
  command_text?: string;
  error?: string;
  active_route?: string;
  app_state?: string;
  meta?: Record<string, unknown>;
};

export type AxonSpeakRequest = {
  text: string;
  preferred_provider?: AxonVoiceProvider | string;
  voice_identity?: string;
};

export type AxonSpeakResponse = {
  provider: AxonVoiceProvider | string;
  voice_identity?: string;
  detail?: string;
  media_type: string;
  audio_base64: string;
};
