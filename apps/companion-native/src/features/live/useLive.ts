import { useCallback, useState } from 'react';

import { fetchLiveSnapshot } from '@/api/live';
import { CompanionConfig, CompanionLiveSnapshot } from '@/types/companion';

export function useLive(config: CompanionConfig) {
  const [snapshot, setSnapshot] = useState<CompanionLiveSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchLiveSnapshot(config);
      setSnapshot(next || null);
      return next || null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load live Axon state');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [config]);

  return { snapshot, loading, error, refresh, setSnapshot, setError };
}
