import Constants from 'expo-constants';

import { CompanionConfig, CompanionTokenPair } from '@/types/companion';
import {
  COMPANION_SESSION_EXPIRED_MESSAGE,
  isCompanionAuthErrorMessage,
} from '@/features/auth/sessionState';

const DEFAULT_BASE_URL = 'http://127.0.0.1:7734';
const DEFAULT_AXON_PORT = '7734';

type ExpoExtraConfig = {
  apiBaseUrl?: unknown;
  expoClient?: {
    hostUri?: unknown;
    debuggerHost?: unknown;
  } | null;
};

type ExpoManifestLike = {
  extra?: ExpoExtraConfig | null;
  hostUri?: unknown;
  debuggerHost?: unknown;
};

type ExpoConstantsLike = {
  expoConfig?: ExpoManifestLike | null;
  manifest?: ExpoManifestLike | null;
  manifest2?: ExpoManifestLike | null;
};

function readExpoConstants(): ExpoConstantsLike {
  return (Constants as unknown as ExpoConstantsLike | null | undefined) || {};
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

function readExpoExtraApiBaseUrl(): string {
  const { expoConfig, manifest, manifest2 } = readExpoConstants();
  const configExtra = expoConfig?.extra;
  const manifestExtra = manifest?.extra;
  const manifest2Extra = manifest2?.extra;
  const candidate = (
    configExtra?.apiBaseUrl
    || manifestExtra?.apiBaseUrl
    || manifest2Extra?.apiBaseUrl
  );
  return typeof candidate === 'string' ? normalizeBaseUrl(candidate) : '';
}

function readExpoHostUri(): string {
  const { expoConfig, manifest, manifest2 } = readExpoConstants();
  const hostCandidate = (
    expoConfig?.hostUri
    || expoConfig?.debuggerHost
    || manifest?.hostUri
    || manifest?.debuggerHost
    || manifest2?.extra?.expoClient?.hostUri
    || manifest2?.extra?.expoClient?.debuggerHost
    || manifest2?.hostUri
    || manifest2?.debuggerHost
  );
  return typeof hostCandidate === 'string' ? hostCandidate : '';
}

function deriveBaseUrlFromHostUri(hostUri: string): string {
  const trimmed = String(hostUri || '').trim();
  if (!trimmed) return '';
  let host = trimmed.replace(/^exp:\/\//i, '').replace(/^https?:\/\//i, '');
  host = host.split('/')[0];
  const hostname = host.split(':')[0];
  if (!hostname) return '';
  return `http://${hostname}:${DEFAULT_AXON_PORT}`;
}

function isLoopbackBaseUrl(value: string): boolean {
  const normalized = normalizeBaseUrl(value);
  return (
    normalized.includes('127.0.0.1')
    || normalized.includes('localhost')
    || normalized.includes('[::1]')
  );
}

export function getSuggestedApiBaseUrl(): string {
  const explicit = normalizeBaseUrl(
    readExpoExtraApiBaseUrl()
    || process.env.EXPO_PUBLIC_AXON_API_BASE_URL
    || '',
  );
  const derived = normalizeBaseUrl(deriveBaseUrlFromHostUri(readExpoHostUri()));
  const suggested = explicit
    ? (isLoopbackBaseUrl(explicit) && derived ? derived : explicit)
    : (derived || DEFAULT_BASE_URL);
  return suggested;
}

export function getApiBaseUrl(config?: CompanionConfig): string {
  const configured = normalizeBaseUrl(config?.apiBaseUrl || '');
  if (configured) {
    return configured;
  }
  return getSuggestedApiBaseUrl();
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

function normalizeTransportError(error: unknown): Error {
  if (error instanceof Error) {
    const message = String(error.message || '').trim().toLowerCase();
    if (error.name === 'AbortError' || message.includes('aborted')) {
      return new Error('Axon request timed out.');
    }
    if (message.includes('network request failed') || message.includes('load failed')) {
      return new Error('Unable to reach live Axon.');
    }
    return error;
  }
  return new Error('Axon request failed.');
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
    } catch (error) {
      throw normalizeTransportError(error);
    }
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
