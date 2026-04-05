import { Dispatch, SetStateAction, useEffect, useRef, useState } from 'react';

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

const BOOTSTRAP_IDENTITY_TIMEOUT_MS = 12_000;
const BOOTSTRAP_REFRESH_TIMEOUT_MS = 10_000;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  return new Promise<T>((resolve, reject) => {
    timeout = setTimeout(() => {
      reject(new Error(message));
    }, timeoutMs);
    promise.then((value) => {
      if (timeout) clearTimeout(timeout);
      resolve(value);
    }).catch((err) => {
      if (timeout) clearTimeout(timeout);
      reject(err);
    });
  });
}

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
  const wasVerifiedRef = useRef(false);
  const authFailureRef = useRef(0);

  useEffect(() => {
    if (!config.accessToken) {
      setVerifiedPairing(false);
      setVerifyingPairing(false);
      setBootstrapError(null);
      wasVerifiedRef.current = false;
      authFailureRef.current = 0;
      return;
    }
    let cancelled = false;

    (async () => {
      setVerifyingPairing(true);
      try {
        let activeConfig = config;
        let identity = await withTimeout(
          fetchCompanionIdentity(activeConfig),
          BOOTSTRAP_IDENTITY_TIMEOUT_MS,
          'Axon Online link check timed out.',
        );
        if ((!identity.device || !identity.auth_session) && activeConfig.tokenPair?.refresh_token) {
          const restored = await restoreSession({ force: true });
          if (restored) {
            activeConfig = restored;
            identity = await withTimeout(
              fetchCompanionIdentity(activeConfig),
              BOOTSTRAP_IDENTITY_TIMEOUT_MS,
              'Axon Online link check timed out.',
            );
          }
        }
        if (!identity.device || !identity.auth_session) {
          throw new Error(COMPANION_SESSION_EXPIRED_MESSAGE);
        }
        if (cancelled) return;
        setVerifiedPairing(true);
        wasVerifiedRef.current = true;
        authFailureRef.current = 0;
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
        void Promise.allSettled([
          withTimeout(
            refreshMission(nextSession?.workspace_id ?? activeConfig.workspaceId ?? null, nextSession?.id ?? activeConfig.sessionId ?? null),
            BOOTSTRAP_REFRESH_TIMEOUT_MS,
            'Mission Control refresh timed out.',
          ),
          withTimeout(
            refreshControl(),
            BOOTSTRAP_REFRESH_TIMEOUT_MS,
            'Operator control refresh timed out.',
          ),
          withTimeout(
            (async () => {
              const [status, providerKeys] = await Promise.all([
                fetchMobileVaultStatus(activeConfig),
                fetchMobileVaultProviderKeys(activeConfig),
              ]);
              if (cancelled) return;
              setVaultStatus(status);
              setVaultProviderKeys(providerKeys);
            })(),
            BOOTSTRAP_REFRESH_TIMEOUT_MS,
            'Vault refresh timed out.',
          ),
        ]).then((settled) => {
          if (cancelled) return;
          const failed = settled.find((item) => item.status === 'rejected') as PromiseRejectedResult | undefined;
          if (failed?.reason) {
            setBootstrapError(failed.reason instanceof Error ? failed.reason.message : 'Axon Online could not load Mission Control.');
          }
        });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Unable to reach live Axon.';
          const authError = isCompanionAuthErrorMessage(message);
          if (authError) {
            authFailureRef.current += 1;
          }
          const shouldDrop = authError && authFailureRef.current >= 2;
          if (shouldDrop || !wasVerifiedRef.current) {
            setVerifiedPairing(false);
          }
          setBootstrapError(message);
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
    config.tokenPair?.refresh_token,
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
