import { axonRequest } from './client';
import {
  CompanionAuthSession,
  CompanionConfig,
  CompanionDevice,
  CompanionPairResponse,
  CompanionPresence,
  CompanionSession,
  PushSubscriptionRequest,
  VoiceTurnRequest,
  VoiceTurnResponse,
} from '@/types/companion';

export async function fetchCompanionStatus(config?: CompanionConfig) {
  return axonRequest<{ status: string; counts: Record<string, number> }>('/api/companion/status', {}, config);
}

export async function fetchCompanionIdentity(config?: CompanionConfig) {
  return axonRequest<{ device: CompanionDevice | null; auth_session: CompanionAuthSession | null; presence: CompanionPresence | null; sessions: CompanionSession[] }>('/api/companion/identity', {}, config);
}

export async function pairCompanionDevice(
  payload: { deviceName: string; deviceKey: string; pin?: string; platform?: string; model?: string; osVersion?: string },
  config?: CompanionConfig,
) {
  return axonRequest<CompanionPairResponse>(
    '/api/companion/auth/pair',
    {
      method: 'POST',
      body: JSON.stringify({
        device_key: payload.deviceKey,
        name: payload.deviceName,
        pin: payload.pin || '',
        kind: 'mobile',
        platform: payload.platform || 'expo',
        model: payload.model || '',
        os_version: payload.osVersion || '',
        ttl_seconds: 60 * 60 * 24 * 30,
      }),
    },
    config,
  );
}

export async function refreshCompanionSession(refresh_token: string, config?: CompanionConfig) {
  return axonRequest<CompanionPairResponse>(
    '/api/companion/auth/refresh',
    {
      method: 'POST',
      body: JSON.stringify({ refresh_token, ttl_seconds: 60 * 60 * 24 * 30 }),
    },
    config,
  );
}

export async function restoreCompanionDevice(
  payload: { deviceKey: string; restoreToken: string },
  config?: CompanionConfig,
) {
  return axonRequest<CompanionPairResponse>(
    '/api/companion/auth/restore',
    {
      method: 'POST',
      body: JSON.stringify({
        device_key: payload.deviceKey,
        restore_token: payload.restoreToken,
        ttl_seconds: 60 * 60 * 24 * 30,
      }),
    },
    config,
  );
}

export async function fetchCurrentPresence(config?: CompanionConfig) {
  return axonRequest<{ presence: CompanionPresence | null }>('/api/companion/presence/current', {}, config);
}

export async function sendPresenceHeartbeat(
  payload: Partial<CompanionPresence> & { device_id?: number },
  config?: CompanionConfig,
) {
  return axonRequest<{ presence: CompanionPresence }>(
    '/api/companion/presence/heartbeat',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function listCompanionSessions(config?: CompanionConfig) {
  return axonRequest<{ sessions: CompanionSession[] }>('/api/companion/sessions', {}, config);
}

export async function upsertCompanionSession(
  payload: Partial<CompanionSession> & { workspace_id?: number | null; summary?: string; active_task?: string },
  config?: CompanionConfig,
) {
  return axonRequest<{ session: CompanionSession }>(
    '/api/companion/sessions',
    { method: 'POST', body: JSON.stringify(payload) },
    config,
  );
}

export async function resumeCompanionSession(session_id: number, config?: CompanionConfig) {
  return axonRequest<{ session: CompanionSession }>(
    `/api/companion/sessions/${session_id}/resume`,
    { method: 'POST', body: JSON.stringify({}) },
    config,
  );
}

export async function sendVoiceTurn(payload: VoiceTurnRequest, config?: CompanionConfig) {
  return axonRequest<VoiceTurnResponse>(
    '/api/companion/voice/turns',
    { method: 'POST', body: JSON.stringify(payload) },
    config,
  );
}

export async function registerPushSubscription(payload: PushSubscriptionRequest, config?: CompanionConfig) {
  return axonRequest<{ subscription: unknown }>(
    '/api/companion/push/subscriptions',
    { method: 'POST', body: JSON.stringify(payload) },
    config,
  );
}
