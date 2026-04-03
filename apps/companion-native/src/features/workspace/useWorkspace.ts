import { useCallback, useState } from 'react';

import { fetchConnectorOverview } from '@/api/workspace';
import { CompanionConfig, WorkspaceSummary } from '@/types/companion';

export function useWorkspace(config: CompanionConfig) {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchConnectorOverview(config);
      setWorkspaces(next.workspaces || []);
      return next.workspaces || [];
    } finally {
      setLoading(false);
    }
  }, [config]);

  return { workspaces, loading, refresh, setWorkspaces };
}

