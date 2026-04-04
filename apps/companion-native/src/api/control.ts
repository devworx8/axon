import { axonRequest } from './client';
import {
  ActionReceipt,
  CompanionConfig,
  ControlCapability,
  RiskChallenge,
  TrustSnapshot,
  TypedActionRequest,
  TypedActionResult,
} from '@/types/companion';

export async function fetchMobileTrust(config?: CompanionConfig) {
  return axonRequest<{ trust: TrustSnapshot; receipts: ActionReceipt[] }>(
    '/api/mobile/control/trust',
    {},
    config,
  );
}

export async function createMobileElevation(
  payload: {
    target_risk_tier?: string;
    verified_via?: string;
    ttl_minutes?: number;
    meta?: Record<string, unknown>;
  },
  config?: CompanionConfig,
) {
  return axonRequest<{ trust: TrustSnapshot }>(
    '/api/mobile/control/elevate',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function fetchControlCapabilities(config?: CompanionConfig) {
  return axonRequest<{ capabilities: ControlCapability[]; trust: TrustSnapshot }>(
    '/api/mobile/actions/capabilities',
    {},
    config,
  );
}

export async function executeMobileAction(payload: TypedActionRequest, config?: CompanionConfig) {
  return axonRequest<TypedActionResult>(
    '/api/mobile/actions/execute',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function fetchActionReceipts(config?: CompanionConfig, limit = 20) {
  return axonRequest<{ receipts: ActionReceipt[] }>(
    `/api/mobile/actions/receipts?limit=${Math.max(1, Math.min(limit, 100))}`,
    {},
    config,
  );
}

export async function fetchRiskChallenges(config?: CompanionConfig, status = 'pending', limit = 20) {
  return axonRequest<{ challenges: RiskChallenge[] }>(
    `/api/mobile/challenges?status=${encodeURIComponent(status)}&limit=${Math.max(1, Math.min(limit, 100))}`,
    {},
    config,
  );
}

export async function confirmRiskChallenge(challengeId: number, config?: CompanionConfig) {
  return axonRequest<{ challenge: RiskChallenge; result: TypedActionResult }>(
    `/api/mobile/challenges/${challengeId}/confirm`,
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
    config,
  );
}

export async function rejectRiskChallenge(challengeId: number, config?: CompanionConfig) {
  return axonRequest<{ challenge: RiskChallenge }>(
    `/api/mobile/challenges/${challengeId}/reject`,
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
    config,
  );
}
