import { axonRequest } from './client';
import { CompanionConfig, VaultProviderKeys, VaultStatus } from '@/types/companion';

export async function fetchMobileVaultStatus(config?: CompanionConfig) {
  return axonRequest<VaultStatus>('/api/mobile/vault/status', {}, config);
}

export async function fetchMobileVaultProviderKeys(config?: CompanionConfig) {
  return axonRequest<VaultProviderKeys>('/api/mobile/vault/provider-keys', {}, config);
}

export async function unlockMobileVault(
  payload: { master_password: string; totp_code: string; remember_me?: boolean },
  config?: CompanionConfig,
) {
  return axonRequest<{ unlocked: boolean; session_ttl: number; ttl_label: string }>(
    '/api/mobile/vault/unlock',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function unlockMobileVaultWithBiometric(
  payload: { master_password: string; remember_me?: boolean; verified_via?: string },
  config?: CompanionConfig,
) {
  return axonRequest<{ unlocked: boolean; session_ttl: number; ttl_label: string }>(
    '/api/mobile/vault/unlock/biometric',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function lockMobileVault(config?: CompanionConfig) {
  return axonRequest<{ locked: boolean }>(
    '/api/mobile/vault/lock',
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
    config,
  );
}
