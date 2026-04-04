import { axonRequest } from './client';
import { CompanionConfig, PlatformSnapshot } from '@/types/companion';

function missionQuery(workspaceId?: number | null, sessionId?: number | null) {
  const params = new URLSearchParams();
  if (workspaceId) params.set('workspace_id', String(workspaceId));
  if (sessionId) params.set('session_id', String(sessionId));
  const suffix = params.toString();
  return suffix ? `?${suffix}` : '';
}

export async function fetchMissionSnapshot(
  config?: CompanionConfig,
  workspaceId?: number | null,
  sessionId?: number | null,
) {
  return axonRequest<PlatformSnapshot>(
    `/api/mobile/mission/snapshot${missionQuery(workspaceId, sessionId)}`,
    {},
    config,
  );
}

export async function fetchMissionDigest(
  config?: CompanionConfig,
  workspaceId?: number | null,
  sessionId?: number | null,
) {
  return axonRequest<{ digest: string; snapshot: PlatformSnapshot }>(
    `/api/mobile/mission/digest${missionQuery(workspaceId, sessionId)}`,
    {},
    config,
  );
}
