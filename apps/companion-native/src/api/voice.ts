import { Platform } from 'react-native';

import { getApiBaseUrl } from './client';
import { CompanionConfig, LocalVoiceStatus } from '@/types/companion';

export async function fetchVoiceStatus(config?: CompanionConfig) {
  const response = await fetch(`${getApiBaseUrl(config)}/api/voice/status`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Axon voice status failed: ${response.status}`);
  }
  return response.json() as Promise<LocalVoiceStatus>;
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

  const response = await fetch(
    `${getApiBaseUrl(config)}/api/voice/transcribe?language=${encodeURIComponent(language)}`,
    {
      method: 'POST',
      body: formData,
      headers: {
        Accept: 'application/json',
      },
    },
  );
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(body || `Axon voice transcription failed: ${response.status}`);
  }
  return response.json() as Promise<{ text: string; engine: string; language: string }>;
}
