import { useCallback, useEffect, useState } from 'react';

import { pairCompanionDevice, refreshCompanionSession } from '@/api/companion';
import { CompanionConfig } from '@/types/companion';
import { withTokenPair } from '@/api/client';
import {
  clearCompanionSession,
  companionRefreshDelayMs,
  COMPANION_SESSION_EXPIRED_MESSAGE,
  isCompanionAuthErrorMessage,
  shouldRefreshCompanionSession,
} from '@/features/auth/sessionState';

function ensureDeviceKey(existing?: string) {
  if (existing && existing.trim()) {
    return existing.trim();
  }
  return `companion-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useAuth(config: CompanionConfig, onConfigChange: (next: CompanionConfig) => void) {
  const [pairing, setPairing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pair = useCallback(async (deviceName: string, pin = '') => {
    setPairing(true);
    setError(null);
    try {
      const deviceKey = ensureDeviceKey(config.deviceKey);
      const result = await pairCompanionDevice({ deviceName, deviceKey, pin }, config);
      onConfigChange(
        withTokenPair(
          {
            ...config,
            deviceId: result.device.id,
            deviceKey,
            deviceName: result.device.name,
          },
          result,
        ),
      );
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing failed');
      throw err;
    } finally {
      setPairing(false);
    }
  }, [config, onConfigChange]);

  const refresh = useCallback(async (refreshToken: string) => {
    setRefreshing(true);
    setError(null);
    try {
      const result = await refreshCompanionSession(refreshToken, config);
      const nextConfig = withTokenPair(
        {
          ...config,
          deviceId: config.deviceId ?? result.auth_session.device_id,
        },
        result,
      );
      onConfigChange(nextConfig);
      return result;
    } finally {
      setRefreshing(false);
    }
  }, [config, onConfigChange]);

  const restoreSession = useCallback(async (options?: { force?: boolean; clearOnFailure?: boolean }) => {
    const refreshToken = String(config.tokenPair?.refresh_token || '').trim();
    if (!refreshToken) {
      return null;
    }
    if (!options?.force && !shouldRefreshCompanionSession(config)) {
      return config;
    }
    setRefreshing(true);
    setError(null);
    try {
      const result = await refreshCompanionSession(refreshToken, config);
      const nextConfig = withTokenPair(
        {
          ...config,
          deviceId: config.deviceId ?? result.auth_session.device_id,
        },
        result,
      );
      onConfigChange(nextConfig);
      return nextConfig;
    } catch (err) {
      const message = err instanceof Error ? err.message : COMPANION_SESSION_EXPIRED_MESSAGE;
      setError(message);
      if (options?.clearOnFailure !== false || isCompanionAuthErrorMessage(message)) {
        onConfigChange(clearCompanionSession(config));
      }
      return null;
    } finally {
      setRefreshing(false);
    }
  }, [config, onConfigChange]);

  useEffect(() => {
    const delayMs = companionRefreshDelayMs(config.tokenPair);
    if (delayMs == null) return undefined;
    const timer = setTimeout(() => {
      restoreSession({ clearOnFailure: false }).catch(() => undefined);
    }, delayMs);
    return () => clearTimeout(timer);
  }, [config.tokenPair, restoreSession]);

  return { pair, refresh, restoreSession, pairing, refreshing, error };
}
