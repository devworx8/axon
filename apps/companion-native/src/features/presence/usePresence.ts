import { useCallback, useState } from 'react';

import { fetchCurrentPresence, sendPresenceHeartbeat } from '@/api/companion';
import { CompanionConfig, CompanionPresence } from '@/types/companion';

export function usePresence(config: CompanionConfig) {
  const [presence, setPresence] = useState<CompanionPresence | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchCurrentPresence(config);
      setPresence(next.presence || null);
      return next.presence || null;
    } finally {
      setLoading(false);
    }
  }, [config]);

  const heartbeat = useCallback(async (
    workspaceId?: number | null,
    sessionId?: number | null,
    voiceState: string = 'idle',
    activeRoute: string = '',
  ) => {
    const next = await sendPresenceHeartbeat({
      device_id: config.deviceId ?? undefined,
      workspace_id: workspaceId ?? null,
      session_id: sessionId ?? null,
      voice_state: voiceState,
      active_route: activeRoute,
    }, config);
    setPresence(next.presence);
    return next.presence;
  }, [config]);

  return { presence, loading, refresh, heartbeat, setPresence };
}
