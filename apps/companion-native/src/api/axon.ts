import { axonRequest } from './client';
import {
  AxonArmRequest,
  AxonDisarmRequest,
  AxonEventRequest,
  AxonModeStatus,
  AxonSpeakRequest,
  AxonSpeakResponse,
  CompanionConfig,
  CompanionPresence,
} from '@/types/companion';

export async function fetchAxonStatus(config?: CompanionConfig) {
  return axonRequest<{ axon: AxonModeStatus }>('/api/mobile/axon/status', {}, config);
}

export async function armAxonMode(payload: AxonArmRequest, config?: CompanionConfig) {
  return axonRequest<{ axon: AxonModeStatus; presence: CompanionPresence | null }>(
    '/api/mobile/axon/arm',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function disarmAxonMode(payload: AxonDisarmRequest = {}, config?: CompanionConfig) {
  return axonRequest<{ axon: AxonModeStatus; presence: CompanionPresence | null }>(
    '/api/mobile/axon/disarm',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function sendAxonEvent(payload: AxonEventRequest, config?: CompanionConfig) {
  return axonRequest<{ axon: AxonModeStatus; presence: CompanionPresence | null }>(
    '/api/mobile/axon/event',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}

export async function speakAxonReply(payload: AxonSpeakRequest, config?: CompanionConfig) {
  return axonRequest<AxonSpeakResponse>(
    '/api/mobile/axon/speak',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    config,
  );
}
