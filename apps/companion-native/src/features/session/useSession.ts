import { useCallback, useState } from 'react';

import { listCompanionSessions, resumeCompanionSession, upsertCompanionSession } from '@/api/companion';
import { CompanionConfig, CompanionSession } from '@/types/companion';

export function useSession(config: CompanionConfig) {
  const [sessions, setSessions] = useState<CompanionSession[]>([]);
  const [activeSession, setActiveSession] = useState<CompanionSession | null>(null);

  const refresh = useCallback(async () => {
    const next = await listCompanionSessions(config);
    setSessions(next.sessions || []);
    setActiveSession((next.sessions || [])[0] || null);
    return next.sessions || [];
  }, [config]);

  const resume = useCallback(async (sessionId: number) => {
    const next = await resumeCompanionSession(sessionId, config);
    setActiveSession(next.session);
    return next.session;
  }, [config]);

  const ensure = useCallback(async (workspaceId?: number | null, summary = 'Companion session active') => {
    const next = await upsertCompanionSession(
      {
        workspace_id: workspaceId ?? config.workspaceId ?? null,
        current_route: '/voice',
        current_view: 'voice',
        active_task: 'Voice companion session',
        summary,
        status: 'active',
        mode: 'voice',
      },
      config,
    );
    setActiveSession(next.session);
    setSessions(current => [next.session, ...current.filter(item => item.id !== next.session.id)]);
    return next.session;
  }, [config]);

  return { sessions, activeSession, refresh, resume, ensure, setActiveSession, setSessions };
}
