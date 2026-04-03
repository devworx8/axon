import { useCallback, useState } from 'react';

import { CompanionConfig } from '@/types/companion';

export type CompanionSettings = {
  voiceEnabled: boolean;
  alwaysListening: boolean;
  preferredWorkspaceId: number | null;
};

const DEFAULT_SETTINGS: CompanionSettings = {
  voiceEnabled: true,
  alwaysListening: false,
  preferredWorkspaceId: null,
};

export function useSettings(config: CompanionConfig, onConfigChange: (next: CompanionConfig) => void) {
  const [settings, setSettings] = useState<CompanionSettings>(DEFAULT_SETTINGS);

  const setPreferredWorkspaceId = useCallback((workspaceId: number | null) => {
    setSettings(current => ({ ...current, preferredWorkspaceId: workspaceId }));
    onConfigChange({ ...config, workspaceId });
  }, [config, onConfigChange]);

  return { settings, setSettings, setPreferredWorkspaceId };
}

