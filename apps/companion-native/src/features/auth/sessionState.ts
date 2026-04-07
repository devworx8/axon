import { CompanionConfig, CompanionTokenPair } from '@/types/companion';

const COMPANION_REFRESH_MARGIN_MS = 60_000;

export type CompanionLinkState = 'unpaired' | 'checking' | 'linked' | 'offline' | 'repair_required';

export const COMPANION_SESSION_EXPIRED_MESSAGE = 'Axon needs to re-verify this phone before protected routes can continue.';
export const COMPANION_REPAIR_REQUIRED_MESSAGE = 'The saved trust for this phone is no longer valid. Pair it again to restore protected routes.';

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

export function hasStoredCompanionPairing(config: CompanionConfig): boolean {
  const hasDeviceIdentity = Boolean(String(config.deviceKey || '').trim() || Number(config.deviceId || 0) > 0);
  const hasRestorePath = Boolean(
    String(config.accessToken || '').trim()
    || String(config.tokenPair?.refresh_token || '').trim()
    || String(config.restoreToken || '').trim(),
  );
  return hasDeviceIdentity && hasRestorePath;
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
    || lowered.includes('saved device trust is no longer valid')
    || lowered.includes('restore token')
    || lowered.includes('device trust')
    || lowered.includes('device revoked')
    || lowered.includes('pair this device again')
    || lowered.includes('session expired')
  );
}

export function companionAuthBannerMessage(value?: string | null): string {
  if (isCompanionRepairRequiredMessage(value)) {
    return COMPANION_REPAIR_REQUIRED_MESSAGE;
  }
  return COMPANION_SESSION_EXPIRED_MESSAGE;
}

export function isCompanionRepairRequiredMessage(value?: string | null): boolean {
  const lowered = String(value || '').trim().toLowerCase();
  if (!lowered) {
    return false;
  }
  return (
    lowered.includes('saved device trust is no longer valid')
    || lowered.includes('pair this device again')
    || lowered.includes('restore token')
    || lowered.includes('device trust')
    || lowered.includes('device revoked')
    || lowered.includes('invalid refresh token')
  );
}

export function isCompanionOfflineErrorMessage(value?: string | null): boolean {
  const lowered = String(value || '').trim().toLowerCase();
  if (!lowered) {
    return false;
  }
  return (
    lowered.includes('unable to reach live axon')
    || lowered.includes('timed out')
    || lowered.includes('timeout')
    || lowered.includes('offline')
    || lowered.includes('network request failed')
    || lowered.includes('load failed')
    || lowered.includes('fetch failed')
    || lowered.includes('failed to fetch')
    || lowered.includes('aborted')
  );
}
