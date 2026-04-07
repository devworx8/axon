import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { LocalVoiceStatus } from '@/types/companion';
import { isVoiceTranscriptionReady } from './voiceReadiness';

export function VoiceCaptureCard({
  voiceStatus,
  checkingStatus,
  isRecording,
  transcribing,
  durationLabel,
  transcript,
  engine,
  error,
  onStart,
  onStop,
  onRefresh,
}: {
  voiceStatus?: LocalVoiceStatus | null;
  checkingStatus?: boolean;
  isRecording?: boolean;
  transcribing?: boolean;
  durationLabel?: string;
  transcript?: string;
  engine?: string;
  error?: string | null;
  onStart?: () => void;
  onStop?: () => void;
  onRefresh?: () => void;
}) {
  const liveReady = isVoiceTranscriptionReady(voiceStatus);
  const statusLabel = checkingStatus
    ? 'Checking'
    : isRecording
      ? `Recording ${durationLabel || '0:00'}`
      : transcribing
        ? 'Transcribing'
        : liveReady
          ? 'Live voice ready'
          : 'Voice unavailable';

  return (
    <SurfaceCard>
      <SurfaceHeader
        title="Live microphone loop"
        subtitle="Record on the phone, transcribe on Axon, then run the transcript through the mobile command bus."
      />
      <View style={styles.pills}>
        <StatusPill label={statusLabel} tone={isRecording ? 'danger' : transcribing ? 'warn' : liveReady ? 'ok' : 'neutral'} />
        {voiceStatus?.preferred_mode ? <StatusPill label={String(voiceStatus.preferred_mode)} tone="accent" /> : null}
        {engine ? <StatusPill label={engine} tone="neutral" /> : null}
      </View>
      <Text style={styles.detail}>
        {voiceStatus?.detail || 'Axon will use local voice services when available and fall back to typed commands when they are not.'}
      </Text>
      <View style={styles.actions}>
        {isRecording ? (
          <Pressable onPress={onStop} style={styles.primaryAction}>
            <Text style={styles.primaryText}>{transcribing ? 'Transcribing…' : 'Stop and run'}</Text>
          </Pressable>
        ) : (
          <Pressable onPress={onStart} disabled={!liveReady || transcribing} style={[styles.primaryAction, (!liveReady || transcribing) ? styles.disabled : null]}>
            <Text style={styles.primaryText}>{checkingStatus ? 'Checking…' : 'Start listening'}</Text>
          </Pressable>
        )}
        <Pressable onPress={onRefresh} style={styles.secondaryAction}>
          <Text style={styles.secondaryText}>Refresh voice</Text>
        </Pressable>
      </View>
      {transcript ? (
        <View style={styles.transcriptBlock}>
          <Text style={styles.label}>Last live transcript</Text>
          <Text style={styles.transcript}>{transcript}</Text>
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  detail: {
    color: '#94a3b8',
    fontSize: 13,
    lineHeight: 19,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  primaryText: {
    color: '#08111f',
    fontWeight: '800',
  },
  secondaryAction: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  secondaryText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.6,
  },
  transcriptBlock: {
    gap: 6,
  },
  label: {
    color: '#7dd3fc',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  transcript: {
    color: '#e5eefb',
    fontSize: 14,
    lineHeight: 20,
  },
  error: {
    color: '#fda4af',
    fontSize: 12,
    lineHeight: 18,
  },
});
