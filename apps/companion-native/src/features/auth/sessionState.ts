import { CompanionConfig, CompanionTokenPair } from '@/types/companion';

const COMPANION_REFRESH_MARGIN_MS = 60_000;

export const COMPANION_SESSION_EXPIRED_MESSAGE = 'Mobile operator session expired. Pair this device again.';

function parseExpiryMs(value?: string): number | null {
  const raw = String(value || '').trim();
  if (!raw) {
    return null;
  }
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export function companionRefreshDelayMs(tokenPair?: CompanionTokenPair, nowMs = Date.now()): number | null {
  if (!tokenPair?.refresh_token) {
    return null;
  }
  const expiryMs = parseExpiryMs(tokenPair.expires_at);
  if (expiryMs == null) {
    return 0;
  }
  return Math.max(0, expiryMs - nowMs - COMPANION_REFRESH_MARGIN_MS);
}

export function shouldRefreshCompanionSession(config: CompanionConfig, nowMs = Date.now()): boolean {
  if (!config.tokenPair?.refresh_token) {
    return false;
  }
  if (!String(config.accessToken || '').trim()) {
    return true;
  }
  const delayMs = companionRefreshDelayMs(config.tokenPair, nowMs);
  return delayMs !== null && delayMs <= 0;
}

export function clearCompanionSession(config: CompanionConfig): CompanionConfig {
  return {
    ...config,
    accessToken: '',
    tokenPair: undefined,
    sessionId: null,
  };
}

export function isCompanionAuthErrorMessage(value?: string | null): boolean {
  const lowered = String(value || '').trim().toLowerCase();
  if (!lowered) {
    return false;
  }
  return (
    lowered.includes('companion auth token required')
    || lowered.includes('authentication required')
    || lowered.includes('invalid refresh token')
    || lowered.includes('pair this device again')
    || lowered.includes('session expired')
  );
}
