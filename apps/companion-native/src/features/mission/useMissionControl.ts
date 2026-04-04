import { useCallback, useState } from 'react';

import { fetchMissionSnapshot } from '@/api/mission';
import { CompanionConfig, PlatformSnapshot } from '@/types/companion';

function buildDigest(snapshot: PlatformSnapshot | null): string {
  if (!snapshot) return '';
  const focus = snapshot.focus || {};
  const workspace = focus.workspace || {};
  const attention = snapshot.attention?.summary || {};
  const counts = attention.counts || {};
  const nextRequired = snapshot.next_required_action || null;
  const axon = snapshot.axon || null;
  const lines = [
    `Platform posture: ${String(snapshot.posture || 'healthy').replace(/_/g, ' ')}.`,
    `Focused workspace: ${workspace.name || 'Global context'}.`,
    `Attention: now=${Number(counts.now || 0)}, waiting=${Number(counts.waiting_on_me || 0)}, watch=${Number(counts.watch || 0)}.`,
  ];
  if (axon?.armed) {
    lines.push(`Axon mode: ${String(axon.monitoring_state || 'armed').replace(/_/g, ' ')} on '${axon.wake_phrase || 'Axon'}'.`);
  }
  const title = String(
    (nextRequired as { title?: string; summary?: string } | null)?.title
      || (nextRequired as { title?: string; summary?: string } | null)?.summary
      || '',
  ).trim();
  if (title) {
    lines.push(`Next required action: ${title}.`);
  }
  return lines.join(' ');
}

export function useMissionControl(config: CompanionConfig) {
  const [snapshot, setSnapshot] = useState<PlatformSnapshot | null>(null);
  const [digest, setDigest] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (
    workspaceId?: number | null,
    sessionId?: number | null,
  ) => {
    setLoading(true);
    setError(null);
    try {
      const nextSnapshot = await fetchMissionSnapshot(
        config,
        workspaceId ?? config.workspaceId,
        sessionId ?? config.sessionId,
      );
      setSnapshot(nextSnapshot || null);
      setDigest(buildDigest(nextSnapshot || null));
      return nextSnapshot || null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Mission Control');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [config]);

  return { snapshot, digest, loading, error, refresh, setSnapshot, setDigest, setError };
}
