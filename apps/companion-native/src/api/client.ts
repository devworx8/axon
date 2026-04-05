import { CompanionConfig, CompanionTokenPair } from '@/types/companion';
import {
  COMPANION_SESSION_EXPIRED_MESSAGE,
  isCompanionAuthErrorMessage,
} from '@/features/auth/sessionState';

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

function extractApiErrorMessage(status: number, rawBody: string): string {
  const trimmed = String(rawBody || '').trim();
  let detail = trimmed;

  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const candidate = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof candidate === 'string' && candidate.trim()) {
        detail = candidate.trim();
      }
    } catch {
      detail = trimmed;
    }
  }

  if (!detail) {
    return `Axon request failed: ${status}`;
  }
  if (status === 401 && isCompanionAuthErrorMessage(detail)) {
    return COMPANION_SESSION_EXPIRED_MESSAGE;
  }
  return detail;
}

export async function axonRequest<T>(
  path: string,
  init: RequestInit = {},
  config?: CompanionConfig,
): Promise<T> {
  const headers = new Headers(init.headers || {});
  const isFormData = init.body instanceof FormData;
  if (init.body != null && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  const token = config?.accessToken || config?.tokenPair?.access_token;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  try {
    const response = await fetch(`${getApiBaseUrl(config)}${path}`, {
      ...init,
      headers,
      signal: init.signal || controller.signal,
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(extractApiErrorMessage(response.status, body));
    }
    return response.json() as Promise<T>;
  } finally {
    clearTimeout(timeout);
  }
}

export function withTokenPair(config: CompanionConfig, tokenPair: CompanionTokenPair): CompanionConfig {
  return {
    ...config,
    tokenPair,
    accessToken: tokenPair.access_token,
  };
}
