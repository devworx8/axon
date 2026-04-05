import { Dispatch, SetStateAction, useEffect, useState } from 'react';

import { fetchCompanionIdentity } from '@/api/companion';
import { fetchMobileVaultProviderKeys, fetchMobileVaultStatus } from '@/api/vault';
import {
  clearCompanionSession,
  COMPANION_SESSION_EXPIRED_MESSAGE,
  isCompanionAuthErrorMessage,
} from '@/features/auth/sessionState';
import type {
  CompanionConfig,
  CompanionPresence,
  VaultProviderKeys,
  VaultStatus,
} from '@/types/companion';

type RestoreSession = (options?: { force?: boolean; clearOnFailure?: boolean }) => Promise<CompanionConfig | null>;

export function useCompanionBootstrap({
  config,
  setConfig,
  setDeviceName,
  restoreSession,
  refreshMission,
  refreshControl,
  setPresence,
  setVaultStatus,
  setVaultProviderKeys,
}: {
  config: CompanionConfig;
  setConfig: Dispatch<SetStateAction<CompanionConfig>>;
  setDeviceName: (value: string) => void;
  restoreSession: RestoreSession;
  refreshMission: (workspaceId?: number | null, sessionId?: number | null) => Promise<unknown>;
  refreshControl: () => Promise<unknown>;
  setPresence: (presence: CompanionPresence | null) => void;
  setVaultStatus: (status: VaultStatus | null) => void;
  setVaultProviderKeys: (keys: VaultProviderKeys | null) => void;
}) {
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [verifiedPairing, setVerifiedPairing] = useState(false);
  const [verifyingPairing, setVerifyingPairing] = useState(false);

  useEffect(() => {
    if (!config.accessToken) {
      setVerifiedPairing(false);
      setVerifyingPairing(false);
      setBootstrapError(null);
      return;
    }
    let cancelled = false;

    (async () => {
      setVerifyingPairing(true);
      try {
        let activeConfig = config;
        let identity = await fetchCompanionIdentity(activeConfig);
        if ((!identity.device || !identity.auth_session) && activeConfig.tokenPair?.refresh_token) {
          const restored = await restoreSession({ force: true });
          if (restored) {
            activeConfig = restored;
            identity = await fetchCompanionIdentity(activeConfig);
          }
        }
        if (!identity.device || !identity.auth_session) {
          throw new Error(COMPANION_SESSION_EXPIRED_MESSAGE);
        }
        if (cancelled) return;
        setVerifiedPairing(true);
        setBootstrapError(null);
        const nextDevice = identity.device || null;
        const nextSession = (identity.sessions || [])[0] || null;
        setConfig((current) => ({
          ...current,
          deviceId: nextDevice?.id ?? current.deviceId ?? null,
          deviceKey: nextDevice?.device_key || current.deviceKey || '',
          deviceName: nextDevice?.name || current.deviceName || '',
          sessionId: nextSession?.id ?? current.sessionId ?? null,
          workspaceId: nextSession?.workspace_id ?? current.workspaceId ?? null,
          apiBaseUrl: current.apiBaseUrl || '',
        }));
        if (nextDevice?.name) {
          setDeviceName(nextDevice.name);
        }
        if (identity.presence) {
          setPresence(identity.presence);
        }
        const settled = await Promise.allSettled([
          refreshMission(nextSession?.workspace_id ?? activeConfig.workspaceId ?? null, nextSession?.id ?? activeConfig.sessionId ?? null),
          refreshControl(),
          (async () => {
            const [status, providerKeys] = await Promise.all([
              fetchMobileVaultStatus(activeConfig),
              fetchMobileVaultProviderKeys(activeConfig),
            ]);
            if (cancelled) return;
            setVaultStatus(status);
            setVaultProviderKeys(providerKeys);
          })(),
        ]);
        if (cancelled) return;
        const failed = settled.find((item) => item.status === 'rejected') as PromiseRejectedResult | undefined;
        if (failed?.reason) {
          setBootstrapError(failed.reason instanceof Error ? failed.reason.message : 'Axon Online could not load Mission Control.');
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Unable to reach live Axon.';
          setVerifiedPairing(false);
          setBootstrapError(message);
          if (isCompanionAuthErrorMessage(message)) {
            setConfig((current) => clearCompanionSession(current));
          }
        }
      } finally {
        if (!cancelled) {
          setVerifyingPairing(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    config.accessToken,
    config.apiBaseUrl,
    config.sessionId,
    config.tokenPair?.refresh_token,
    config.workspaceId,
    refreshControl,
    refreshMission,
    restoreSession,
    setConfig,
    setDeviceName,
    setPresence,
    setVaultProviderKeys,
    setVaultStatus,
  ]);

  return { bootstrapError, verifiedPairing, verifyingPairing };
}
