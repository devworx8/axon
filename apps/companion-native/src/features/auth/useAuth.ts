import { useCallback, useEffect, useState } from 'react';

import { pairCompanionDevice, refreshCompanionSession } from '@/api/companion';
import { CompanionConfig } from '@/types/companion';
import { withTokenPair } from '@/api/client';

function ensureDeviceKey(existing?: string) {
  if (existing && existing.trim()) {
    return existing.trim();
  }
  return `companion-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useAuth(config: CompanionConfig, onConfigChange: (next: CompanionConfig) => void) {
  const [pairing, setPairing] = useState(false);
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
    const result = await refreshCompanionSession(refreshToken, config);
    onConfigChange(
      withTokenPair(
        {
          ...config,
          deviceId: config.deviceId ?? result.auth_session.device_id,
        },
        result,
      ),
    );
    return result;
  }, [config, onConfigChange]);

  useEffect(() => {
    if (!config.tokenPair?.refresh_token) return;
  }, [config.tokenPair?.refresh_token]);

  return { pair, refresh, pairing, error };
}
