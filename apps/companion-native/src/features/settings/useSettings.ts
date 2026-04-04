import { useCallback, useEffect, useState } from 'react';

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
  preferredWorkspaceId: null,
  apiBaseUrl: '',
};

export function useSettings(config: CompanionConfig, onConfigChange: (next: CompanionConfig) => void) {
  const [settings, setSettings] = useState<CompanionSettings>({
    ...DEFAULT_SETTINGS,
    preferredWorkspaceId: config.workspaceId ?? null,
    apiBaseUrl: config.apiBaseUrl || '',
  });

  useEffect(() => {
    let cancelled = false;
    loadCompanionSettings().then((stored) => {
      if (cancelled) return;
      setSettings(current => normalizeCompanionSettings({
        ...stored,
        preferredWorkspaceId: current.preferredWorkspaceId ?? stored.preferredWorkspaceId ?? config.workspaceId ?? null,
        apiBaseUrl: current.apiBaseUrl || stored.apiBaseUrl || config.apiBaseUrl || '',
      }));
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [config.apiBaseUrl, config.workspaceId]);

  useEffect(() => {
    saveCompanionSettings(settings).catch(() => undefined);
  }, [settings]);

  useEffect(() => {
    setSettings(current => normalizeCompanionSettings({
      ...current,
      preferredWorkspaceId: config.workspaceId ?? current.preferredWorkspaceId ?? null,
      apiBaseUrl: config.apiBaseUrl || current.apiBaseUrl || '',
    }));
  }, [config.apiBaseUrl, config.workspaceId]);

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
