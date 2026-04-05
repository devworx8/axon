import { Platform } from 'react-native';

import { axonRequest, getApiBaseUrl } from './client';
import { CompanionConfig, LocalVoiceStatus } from '@/types/companion';

export async function fetchVoiceStatus(config?: CompanionConfig) {
  return axonRequest<LocalVoiceStatus>('/api/voice/status', {}, config);
}

export async function transcribeRecordedAudio(
  uri: string,
  options?: {
    language?: string;
    mimeType?: string;
    filename?: string;
    config?: CompanionConfig;
  },
) {
  const language = options?.language || 'en';
  const mimeType = options?.mimeType || 'audio/webm';
  const filename = options?.filename || 'voice.webm';
  const config = options?.config;
  const formData = new FormData();

  if (Platform.OS === 'web') {
    const blob = await fetch(uri).then((response) => response.blob());
    formData.append('file', blob, filename);
  } else {
    formData.append('file', {
      uri,
      name: filename,
      type: mimeType,
    } as unknown as Blob);
  }

  return axonRequest<{ text: string; engine: string; language: string }>(
    `/api/voice/transcribe?language=${encodeURIComponent(language)}`,
    { method: 'POST', body: formData },
    config,
  );
}
