import { axonRequest } from './client';
import { CompanionConfig, CompanionLiveSnapshot } from '@/types/companion';

export async function fetchLiveSnapshot(config?: CompanionConfig) {
  const query = config?.workspaceId ? `?workspace_id=${encodeURIComponent(String(config.workspaceId))}` : '';
  return axonRequest<CompanionLiveSnapshot>(`/api/companion/live${query}`, {}, config);
}
