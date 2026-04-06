import { Dispatch, SetStateAction, useEffect, useState } from 'react';

import { fetchCompanionIdentity } from '@/api/companion';
import { fetchMobileVaultProviderKeys, fetchMobileVaultStatus } from '@/api/vault';
import {
  CompanionLinkState,
  COMPANION_REPAIR_REQUIRED_MESSAGE,
  hasStoredCompanionPairing,
  isCompanionOfflineErrorMessage,
  isCompanionRepairRequiredMessage,
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
const BOOTSTRAP_RETRY_DELAY_MS = 8_000;

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
  refreshMission: (workspaceId?: number | null, sessionId?: number | null, options?: { silent?: boolean }) => Promise<unknown>;
  refreshControl: () => Promise<unknown>;
  setPresence: (presence: CompanionPresence | null) => void;
  setVaultStatus: (status: VaultStatus | null) => void;
  setVaultProviderKeys: (keys: VaultProviderKeys | null) => void;
}) {
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [verifiedPairing, setVerifiedPairing] = useState(false);
  const [verifyingPairing, setVerifyingPairing] = useState(false);
  const [linkState, setLinkState] = useState<CompanionLinkState>('unpaired');
  const [retryNonce, setRetryNonce] = useState(0);

  const storedPairing = hasStoredCompanionPairing(config);
  const canAttemptBootstrap = Boolean(
    String(config.accessToken || '').trim()
    || String(config.tokenPair?.refresh_token || '').trim()
    || (String(config.deviceKey || '').trim() && String(config.restoreToken || '').trim()),
  );

  useEffect(() => {
    if (!storedPairing || linkState !== 'offline' || verifyingPairing) {
      return undefined;
    }
    const timer = setTimeout(() => {
      setRetryNonce((current) => current + 1);
    }, BOOTSTRAP_RETRY_DELAY_MS);
    return () => clearTimeout(timer);
  }, [linkState, storedPairing, verifyingPairing]);

  useEffect(() => {
    if (!canAttemptBootstrap) {
      setVerifiedPairing(false);
      setVerifyingPairing(false);
      setBootstrapError(storedPairing ? COMPANION_REPAIR_REQUIRED_MESSAGE : null);
      setLinkState(storedPairing ? 'repair_required' : 'unpaired');
      return;
    }

    let cancelled = false;

    (async () => {
      setVerifyingPairing(true);
      setBootstrapError(null);
      setLinkState('checking');

      try {
        let activeConfig = config;
        if (!String(activeConfig.accessToken || '').trim()) {
          const restored = await restoreSession({ force: true, clearOnFailure: false });
          if (restored) {
            activeConfig = restored;
          }
        }

        let identity = await withTimeout(
          fetchCompanionIdentity(activeConfig),
          BOOTSTRAP_IDENTITY_TIMEOUT_MS,
          'Axon Online link check timed out.',
        );

        if (
          (!identity.device || !identity.auth_session)
          && (
            String(activeConfig.tokenPair?.refresh_token || '').trim()
            || (String(activeConfig.deviceKey || '').trim() && String(activeConfig.restoreToken || '').trim())
          )
        ) {
          const restored = await restoreSession({ force: true, clearOnFailure: false });
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
          throw new Error(COMPANION_REPAIR_REQUIRED_MESSAGE);
        }
        if (cancelled) return;

        setVerifiedPairing(true);
        setLinkState('linked');
        setBootstrapError(null);

        const nextDevice = identity.device || null;
        const nextSession = (identity.sessions || [])[0] || null;
        setConfig((current) => {
          const nextDeviceId = nextDevice?.id ?? current.deviceId ?? null;
          const nextDeviceKey = nextDevice?.device_key || current.deviceKey || '';
          const nextDeviceName = nextDevice?.name || current.deviceName || '';
          const nextSessionId = nextSession?.id ?? current.sessionId ?? null;
          const nextWorkspaceId = nextSession?.workspace_id ?? current.workspaceId ?? null;
          if (
            current.deviceId === nextDeviceId
            && current.deviceKey === nextDeviceKey
            && current.deviceName === nextDeviceName
            && current.sessionId === nextSessionId
            && current.workspaceId === nextWorkspaceId
            && current.apiBaseUrl
          ) {
            return current;
          }
          return {
            ...current,
            deviceId: nextDeviceId,
            deviceKey: nextDeviceKey,
            deviceName: nextDeviceName,
            sessionId: nextSessionId,
            workspaceId: nextWorkspaceId,
            apiBaseUrl: current.apiBaseUrl || '',
          };
        });

        if (nextDevice?.name) {
          setDeviceName(nextDevice.name);
        }
        if (identity.presence) {
          setPresence(identity.presence);
        }

        void Promise.allSettled([
          withTimeout(
            refreshMission(
              nextSession?.workspace_id ?? activeConfig.workspaceId ?? null,
              nextSession?.id ?? activeConfig.sessionId ?? null,
              { silent: true },
            ),
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
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Unable to reach live Axon.';
        setVerifiedPairing(false);
        setBootstrapError(message);
        if (isCompanionRepairRequiredMessage(message)) {
          setLinkState('repair_required');
          return;
        }
        if (storedPairing || isCompanionOfflineErrorMessage(message)) {
          setLinkState('offline');
          return;
        }
        setLinkState('unpaired');
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
    canAttemptBootstrap,
    config.accessToken,
    config.apiBaseUrl,
    config.deviceKey,
    config.restoreToken,
    config.tokenPair?.refresh_token,
    refreshControl,
    refreshMission,
    restoreSession,
    retryNonce,
    setConfig,
    setDeviceName,
    setPresence,
    setVaultProviderKeys,
    setVaultStatus,
    storedPairing,
  ]);

  return { bootstrapError, verifiedPairing, verifyingPairing, linkState };
}
