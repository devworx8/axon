import * as SecureStore from 'expo-secure-store';

import { CompanionConfig } from '@/types/companion';

const COMPANION_CONFIG_KEY = 'axon.companion.config';

function normalizeConfig(config: CompanionConfig): CompanionConfig {
  return {
    accessToken: config.accessToken || '',
    tokenPair: config.tokenPair,
    deviceId: config.deviceId ?? null,
    deviceKey: config.deviceKey || '',
    deviceName: config.deviceName || '',
    sessionId: config.sessionId ?? null,
    workspaceId: config.workspaceId ?? null,
  };
}

export async function loadCompanionConfig(): Promise<CompanionConfig> {
  const raw = await SecureStore.getItemAsync(COMPANION_CONFIG_KEY);
  if (!raw) {
    return { workspaceId: null, sessionId: null, deviceId: null };
  }
  try {
    return normalizeConfig(JSON.parse(raw) as CompanionConfig);
  } catch {
    return { workspaceId: null, sessionId: null, deviceId: null };
  }
}

export async function saveCompanionConfig(config: CompanionConfig): Promise<void> {
  await SecureStore.setItemAsync(COMPANION_CONFIG_KEY, JSON.stringify(normalizeConfig(config)));
}

export async function clearCompanionConfig(): Promise<void> {
  await SecureStore.deleteItemAsync(COMPANION_CONFIG_KEY);
}
