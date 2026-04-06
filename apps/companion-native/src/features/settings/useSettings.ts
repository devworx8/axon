import { useCallback, useEffect, useRef, useState } from 'react';

import { pushVoiceSettings } from '@/api/axon';
import { getSuggestedApiBaseUrl } from '@/api/client';
import { CompanionConfig } from '@/types/companion';
import { loadCompanionSettings, normalizeCompanionSettings, saveCompanionSettings } from './settingsStore';

export type CompanionSettings = {
  voiceEnabled: boolean;
  alwaysListening: boolean;
  spokenReplies: boolean;
  axonModeEnabled: boolean;
  axonWakePhrase: string;
  axonBootSound: boolean;
  continuousForegroundMonitoring: boolean;
  axonVoiceProvider: 'cloud' | 'local' | 'device';
  axonVoiceIdentity: string;
  azureSpeechKey: string;
  azureSpeechRegion: string;
  voiceSpeechRate: string;
  voiceSpeechPitch: string;
  preferredWorkspaceId: number | null;
  apiBaseUrl: string;
};

const DEFAULT_SETTINGS: CompanionSettings = {
  voiceEnabled: true,
  alwaysListening: true,
  spokenReplies: true,
  axonModeEnabled: true,
  axonWakePhrase: 'Axon',
  axonBootSound: true,
  continuousForegroundMonitoring: true,
  axonVoiceProvider: 'cloud',
  axonVoiceIdentity: '',
  azureSpeechKey: '',
  azureSpeechRegion: 'eastus',
  voiceSpeechRate: '0.85',
  voiceSpeechPitch: '1.04',
  preferredWorkspaceId: null,
  apiBaseUrl: '',
};

export function useSettings(config: CompanionConfig, onConfigChange: (next: CompanionConfig) => void) {
  const suggestedBaseUrl = getSuggestedApiBaseUrl();
  const loopbackPattern = /(127\.0\.0\.1|localhost|\[::1\])/i;
  const [settings, setSettings] = useState<CompanionSettings>({
    ...DEFAULT_SETTINGS,
    preferredWorkspaceId: config.workspaceId ?? null,
    apiBaseUrl: config.apiBaseUrl || suggestedBaseUrl,
  });

  useEffect(() => {
    let cancelled = false;
    loadCompanionSettings().then((stored) => {
      if (cancelled) return;
      const storedBaseUrl = String(stored?.apiBaseUrl || '').trim();
      const normalizedStoredBaseUrl = storedBaseUrl && (!loopbackPattern.test(storedBaseUrl) || !suggestedBaseUrl)
        ? storedBaseUrl
        : (storedBaseUrl ? suggestedBaseUrl : '');
      setSettings(current => normalizeCompanionSettings({
        ...stored,
        preferredWorkspaceId: current.preferredWorkspaceId ?? stored.preferredWorkspaceId ?? config.workspaceId ?? null,
        apiBaseUrl: current.apiBaseUrl || normalizedStoredBaseUrl || config.apiBaseUrl || suggestedBaseUrl,
      }));
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [config.apiBaseUrl, config.workspaceId, suggestedBaseUrl]);

  useEffect(() => {
    saveCompanionSettings(settings).catch(() => undefined);
  }, [settings]);

  /* ── Push voice-relevant settings to backend when changed ── */
  const prevVoiceSettingsRef = useRef('');
  useEffect(() => {
    const voicePayload: Record<string, string | null> = {
      azure_speech_key: settings.azureSpeechKey || null,
      azure_speech_region: settings.azureSpeechRegion || null,
      voice_speech_rate: settings.voiceSpeechRate || null,
      voice_speech_pitch: settings.voiceSpeechPitch || null,
    };
    const sig = JSON.stringify(voicePayload);
    if (sig === prevVoiceSettingsRef.current) return;
    prevVoiceSettingsRef.current = sig;
    if (!config.accessToken) return;
    pushVoiceSettings(voicePayload, config).catch(() => undefined);
  }, [
    settings.azureSpeechKey,
    settings.azureSpeechRegion,
    settings.voiceSpeechRate,
    settings.voiceSpeechPitch,
    config,
  ]);

  useEffect(() => {
    setSettings(current => normalizeCompanionSettings({
      ...current,
      preferredWorkspaceId: config.workspaceId ?? current.preferredWorkspaceId ?? null,
      apiBaseUrl: config.apiBaseUrl || current.apiBaseUrl || suggestedBaseUrl,
    }));
  }, [config.apiBaseUrl, config.workspaceId, suggestedBaseUrl]);

  const setPreferredWorkspaceId = useCallback((workspaceId: number | null) => {
    setSettings(current => ({ ...current, preferredWorkspaceId: workspaceId }));
    onConfigChange({ ...config, workspaceId });
  }, [config, onConfigChange]);

  const setApiBaseUrl = useCallback((apiBaseUrl: string) => {
    setSettings(current => ({ ...current, apiBaseUrl }));
    onConfigChange({ ...config, apiBaseUrl });
  }, [config, onConfigChange]);

  return { settings, setSettings, setPreferredWorkspaceId, setApiBaseUrl };
}
