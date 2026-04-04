import { CompanionConfig, CompanionTokenPair } from '@/types/companion';

const DEFAULT_BASE_URL = 'http://127.0.0.1:7734';

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

export function getApiBaseUrl(config?: CompanionConfig): string {
  const configured = normalizeBaseUrl(config?.apiBaseUrl || '');
  if (configured) {
    return configured;
  }
  return normalizeBaseUrl(process.env.EXPO_PUBLIC_AXON_API_BASE_URL || DEFAULT_BASE_URL);
}

export async function axonRequest<T>(
  path: string,
  init: RequestInit = {},
  config?: CompanionConfig,
): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (init.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  const token = config?.accessToken || config?.tokenPair?.access_token;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(`${getApiBaseUrl(config)}${path}`, {
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
