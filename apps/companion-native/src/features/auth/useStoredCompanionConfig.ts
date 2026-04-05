import { Dispatch, SetStateAction, useEffect, useState } from 'react';

import { loadCompanionConfig, saveCompanionConfig } from '@/features/settings/configStore';
import type { CompanionConfig } from '@/types/companion';

export function useStoredCompanionConfig(
  config: CompanionConfig,
  setConfig: Dispatch<SetStateAction<CompanionConfig>>,
  setDeviceName: (value: string) => void,
) {
  const [configReady, setConfigReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadCompanionConfig()
      .then((stored) => {
        if (cancelled) return;
        setConfig({
          apiBaseUrl: stored.apiBaseUrl || '',
          workspaceId: stored.workspaceId ?? null,
          sessionId: stored.sessionId ?? null,
          deviceId: stored.deviceId ?? null,
          deviceKey: stored.deviceKey || '',
          deviceName: stored.deviceName || '',
          accessToken: stored.accessToken || '',
          tokenPair: stored.tokenPair,
        });
        if (stored.deviceName) {
          setDeviceName(stored.deviceName);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setConfigReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setConfig, setDeviceName]);

  useEffect(() => {
    if (!configReady) return;
    saveCompanionConfig(config).catch(() => undefined);
  }, [config, configReady]);
}
