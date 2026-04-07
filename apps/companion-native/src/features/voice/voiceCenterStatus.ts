export type VoiceIndicatorTone = 'ok' | 'warn' | 'danger' | 'neutral';

type VoiceCenterStatusInput = {
  asleep?: boolean;
  sending?: boolean;
  transcribing?: boolean;
  recording?: boolean;
  speaking?: boolean;
  recordingDuration?: string;
  liveReady?: boolean;
  checkingVoiceStatus?: boolean;
  liveError?: string | null;
};

export function voiceCenterStatusLabel({
  asleep,
  sending,
  transcribing,
  recording,
  speaking,
  recordingDuration,
}: VoiceCenterStatusInput): string {
  if (asleep) return 'Reactor Offline';
  if (sending) return 'Processing…';
  if (transcribing) return 'Transcribing…';
  if (recording) return `Listening ${recordingDuration || ''}`.trim();
  if (speaking) return 'Speaking the result';
  return 'Standing By';
}

export function voiceCenterStatusCaption({
  asleep,
  sending,
  transcribing,
  recording,
  speaking,
  liveReady,
  checkingVoiceStatus,
  liveError,
}: VoiceCenterStatusInput): string {
  if (asleep) return 'TAP THE REACTOR TO RE-ENGAGE';
  if (recording) return 'TAP THE REACTOR TO STOP AND SUBMIT';
  if (transcribing) return 'BUILDING THE TRANSCRIPT';
  if (sending) return 'ROUTING THROUGH AXON';
  if (speaking) return 'REPLY PLAYBACK';
  if (checkingVoiceStatus) return 'REFRESHING THE VOICE LINK';
  if (liveError) return 'VOICE LINK NEEDS ATTENTION';
  if (!liveReady) return 'TAP THE REACTOR TO RETRY VOICE';
  return 'TAP THE REACTOR TO START LISTENING';
}

export function buildVoiceLiveIndicator({
  recording,
  transcribing,
  sending,
  liveReady,
  checkingVoiceStatus,
  liveError,
}: VoiceCenterStatusInput): { label: string; tone: VoiceIndicatorTone } {
  if (recording) {
    return { label: 'Listening', tone: 'danger' };
  }
  if (transcribing || sending) {
    return { label: 'Processing', tone: 'warn' };
  }
  if (checkingVoiceStatus) {
    return { label: 'Checking', tone: 'warn' };
  }
  if (liveError) {
    return { label: 'Retry voice', tone: 'danger' };
  }
  if (liveReady) {
    return { label: 'Voice ready', tone: 'ok' };
  }
  return { label: 'Voice offline', tone: 'neutral' };
}
