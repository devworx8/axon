import { axonRequest } from './client';
import { CompanionConfig, McpServerSpec, McpSessionState } from '@/types/companion';

export async function fetchMcpServers(config?: CompanionConfig) {
  return axonRequest<{ servers: McpServerSpec[]; capabilities: Array<Record<string, unknown>> }>(
    '/api/mcp/servers',
    {},
    config,
  );
}

export async function fetchMcpSessions(config?: CompanionConfig) {
  return axonRequest<{ sessions: McpSessionState[]; hybrid_enabled: boolean }>(
    '/api/mcp/sessions',
    {},
    config,
  );
}

export async function invokeMcpCapability(
  capabilityKey: string,
  payload: { workspace_id?: number | null; arguments?: Record<string, unknown> } = {},
  config?: CompanionConfig,
) {
  return axonRequest<Record<string, unknown>>(
    '/api/mcp/invoke',
    {
      method: 'POST',
      body: JSON.stringify({
        capability_key: capabilityKey,
        workspace_id: payload.workspace_id ?? null,
        arguments: payload.arguments ?? {},
      }),
    },
    config,
  );
}
