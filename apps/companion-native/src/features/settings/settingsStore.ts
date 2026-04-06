import * as SecureStore from 'expo-secure-store';

import type { CompanionSettings } from './useSettings';

const COMPANION_SETTINGS_KEY = 'axon.companion.settings';

export function normalizeCompanionSettings(settings: Partial<CompanionSettings> | null | undefined): CompanionSettings {
  const provider = String(settings?.axonVoiceProvider || 'cloud').trim().toLowerCase();
  const fastVoiceRuntimeMode = String(settings?.fastVoiceRuntimeMode || 'selected_runtime').trim().toLowerCase();
  return {
    voiceEnabled: settings?.voiceEnabled ?? true,
    alwaysListening: settings?.alwaysListening ?? true,
    spokenReplies: settings?.spokenReplies ?? true,
    axonModeEnabled: settings?.axonModeEnabled ?? true,
    axonWakePhrase: String(settings?.axonWakePhrase || 'Axon').trim() || 'Axon',
    axonBootSound: settings?.axonBootSound ?? true,
    continuousForegroundMonitoring: settings?.continuousForegroundMonitoring ?? true,
    axonVoiceProvider: provider === 'local' || provider === 'device' ? provider : 'cloud',
    axonVoiceIdentity: String(settings?.axonVoiceIdentity || '').trim(),
    azureSpeechKey: String(settings?.azureSpeechKey || '').trim(),
    azureSpeechRegion: String(settings?.azureSpeechRegion || 'eastus').trim() || 'eastus',
    fastVoiceRuntimeMode: fastVoiceRuntimeMode === 'auto_fastest' ? 'auto_fastest' : 'selected_runtime',
    voiceSpeechRate: String(settings?.voiceSpeechRate || '0.85').trim() || '0.85',
    voiceSpeechPitch: String(settings?.voiceSpeechPitch || '1.04').trim() || '1.04',
    preferredWorkspaceId: settings?.preferredWorkspaceId ?? null,
    apiBaseUrl: settings?.apiBaseUrl || '',
  };
}

export async function loadCompanionSettings(): Promise<CompanionSettings> {
  const raw = await SecureStore.getItemAsync(COMPANION_SETTINGS_KEY);
  if (!raw) {
    return normalizeCompanionSettings(null);
  }
  try {
    return normalizeCompanionSettings(JSON.parse(raw) as Partial<CompanionSettings>);
  } catch {
    return normalizeCompanionSettings(null);
  }
}

export async function saveCompanionSettings(settings: CompanionSettings): Promise<void> {
  await SecureStore.setItemAsync(
    COMPANION_SETTINGS_KEY,
    JSON.stringify(normalizeCompanionSettings(settings)),
  );
}
