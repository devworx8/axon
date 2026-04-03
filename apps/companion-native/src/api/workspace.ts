import { axonRequest } from './client';
import { CompanionConfig, WorkspaceRelationship, WorkspaceSummary } from '@/types/companion';

export async function fetchConnectorOverview(config?: CompanionConfig) {
  return axonRequest<{ workspaces: WorkspaceSummary[] }>('/api/connectors/overview?limit=20', {}, config);
}

export async function fetchWorkspaceRelationships(config?: CompanionConfig, workspaceId?: number) {
  const path = workspaceId ? `/api/connectors/workspaces/${workspaceId}` : '/api/connectors/overview?limit=20';
  return axonRequest<{ workspace?: WorkspaceSummary; relationships: WorkspaceRelationship[] } | { workspaces: WorkspaceSummary[] }>(path, {}, config);
}

