import { CompanionConfig, CompanionTokenPair } from '@/types/companion';

const DEFAULT_BASE_URL = 'http://127.0.0.1:7734';

export function getApiBaseUrl(): string {
  return process.env.EXPO_PUBLIC_AXON_API_BASE_URL || DEFAULT_BASE_URL;
}

export async function axonRequest<T>(
  path: string,
  init: RequestInit = {},
  config?: CompanionConfig,
): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set('Content-Type', 'application/json');
  const token = config?.accessToken || config?.tokenPair?.access_token;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(body || `Axon request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function withTokenPair(config: CompanionConfig, tokenPair: CompanionTokenPair): CompanionConfig {
  return {
    ...config,
    tokenPair,
    accessToken: tokenPair.access_token,
  };
}

