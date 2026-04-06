import { useCallback, useEffect, useState } from 'react';

import { withTokenPair } from '@/api/client';
import {
  pairCompanionDevice,
  refreshCompanionSession,
  restoreCompanionDevice,
} from '@/api/companion';
import { CompanionConfig, CompanionPairResponse } from '@/types/companion';
import {
  clearCompanionSession,
  companionRefreshDelayMs,
  COMPANION_REPAIR_REQUIRED_MESSAGE,
  COMPANION_SESSION_EXPIRED_MESSAGE,
  isCompanionAuthErrorMessage,
  isCompanionRepairRequiredMessage,
  shouldRefreshCompanionSession,
} from '@/features/auth/sessionState';

function ensureDeviceKey(existing?: string) {
  if (existing && existing.trim()) {
    return existing.trim();
  }
  return `companion-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function applyAuthResult(
  current: CompanionConfig,
  result: CompanionPairResponse,
  deviceKeyOverride?: string,
): CompanionConfig {
  const deviceKey = result.device?.device_key || deviceKeyOverride || current.deviceKey || '';
  const nextDeviceId = result.device?.id ?? current.deviceId ?? result.auth_session.device_id;
  const nextDeviceName = result.device?.name || current.deviceName || '';
  return {
    ...withTokenPair(
      {
        ...current,
        deviceId: nextDeviceId,
        deviceKey,
        deviceName: nextDeviceName,
      },
      result,
    ),
    restoreToken: result.restore_token || current.restoreToken || '',
  };
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
      onConfigChange(applyAuthResult(config, result, deviceKey));
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
      const nextConfig = applyAuthResult(config, result);
      onConfigChange(nextConfig);
      return result;
    } finally {
      setRefreshing(false);
    }
  }, [config, onConfigChange]);

  const restoreSession = useCallback(async (options?: { force?: boolean; clearOnFailure?: boolean }) => {
    const refreshToken = String(config.tokenPair?.refresh_token || '').trim();
    const deviceKey = String(config.deviceKey || '').trim();
    const restoreToken = String(config.restoreToken || '').trim();
    const canRestoreTrust = Boolean(deviceKey && restoreToken);

    if (!options?.force && !shouldRefreshCompanionSession(config)) {
      return config;
    }
    if (!refreshToken && !canRestoreTrust) {
      return null;
    }

    setRefreshing(true);
    setError(null);

    const attemptDeviceRestore = async () => {
      if (!canRestoreTrust) {
        return null;
      }
      const restored = await restoreCompanionDevice({ deviceKey, restoreToken }, config);
      const nextConfig = applyAuthResult(config, restored, deviceKey);
      onConfigChange(nextConfig);
      return nextConfig;
    };

    try {
      if (refreshToken) {
        try {
          const refreshed = await refreshCompanionSession(refreshToken, config);
          const nextConfig = applyAuthResult(config, refreshed);
          onConfigChange(nextConfig);
          return nextConfig;
        } catch (err) {
          const message = err instanceof Error ? err.message : COMPANION_SESSION_EXPIRED_MESSAGE;
          if (!isCompanionAuthErrorMessage(message) || !canRestoreTrust) {
            throw err;
          }
        }
      }

      const restored = await attemptDeviceRestore();
      if (restored) {
        return restored;
      }
      return null;
    } catch (err) {
      let message = err instanceof Error ? err.message : COMPANION_SESSION_EXPIRED_MESSAGE;
      if (isCompanionAuthErrorMessage(message)) {
        message = COMPANION_REPAIR_REQUIRED_MESSAGE;
      }
      setError(message);
      if (options?.clearOnFailure !== false && isCompanionRepairRequiredMessage(message)) {
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
