type VoiceReadinessStatus = {
  transcription_ready?: boolean | null;
  cloud_transcription_available?: boolean | null;
  transcription_available?: boolean | null;
  local_voice_ready?: boolean | null;
};

export function isVoiceTranscriptionReady(status?: VoiceReadinessStatus | null): boolean {
  return Boolean(
    status?.transcription_ready
    || status?.cloud_transcription_available
    || status?.transcription_available
    || status?.local_voice_ready,
  );
}
