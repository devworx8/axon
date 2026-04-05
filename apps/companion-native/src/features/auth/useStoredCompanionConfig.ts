import { Dispatch, SetStateAction, useEffect, useState } from 'react';

import { getSuggestedApiBaseUrl } from '@/api/client';
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
        const suggestedBaseUrl = getSuggestedApiBaseUrl();
        const storedBaseUrl = String(stored.apiBaseUrl || '').trim();
        const loopbackPattern = /(127\.0\.0\.1|localhost|\[::1\])/i;
        const nextBaseUrl = storedBaseUrl
          ? (!loopbackPattern.test(storedBaseUrl) || !suggestedBaseUrl ? storedBaseUrl : suggestedBaseUrl)
          : suggestedBaseUrl;
        setConfig((current) => {
          const currentToken = current.accessToken || current.tokenPair?.access_token || '';
          const storedToken = stored.accessToken || stored.tokenPair?.access_token || '';
          const keepCurrentToken = Boolean(currentToken) && !storedToken;
          const tokenPair = keepCurrentToken ? current.tokenPair : stored.tokenPair;
          const accessToken = keepCurrentToken ? current.accessToken : (stored.accessToken || current.accessToken || '');
          return {
            apiBaseUrl: nextBaseUrl || current.apiBaseUrl || '',
            workspaceId: stored.workspaceId ?? current.workspaceId ?? null,
            sessionId: stored.sessionId ?? current.sessionId ?? null,
            deviceId: stored.deviceId ?? current.deviceId ?? null,
            deviceKey: stored.deviceKey || current.deviceKey || '',
            deviceName: stored.deviceName || current.deviceName || '',
            accessToken,
            tokenPair,
          };
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
