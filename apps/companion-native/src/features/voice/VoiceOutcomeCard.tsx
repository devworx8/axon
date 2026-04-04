import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { useTheme } from '@/theme/ThemeProvider';
import { ApprovalRequired } from '@/types/companion';

type Props = {
  transcript?: string;
  response?: string;
  backend?: string;
  tokensUsed?: number;
  approval?: ApprovalRequired | null;
  error?: string | null;
  onOpenSession?: () => void;
  speaking?: boolean;
  onSpeak?: () => void;
  onStopSpeaking?: () => void;
};

export function VoiceOutcomeCard({
  transcript,
  response,
  backend,
  tokensUsed,
  approval,
  error,
  onOpenSession,
  speaking,
  onSpeak,
  onStopSpeaking,
}: Props) {
  const { colors } = useTheme();

  return (
    <SurfaceCard>
      <SurfaceHeader title="Latest outcome" subtitle="What Axon heard, what it did, and what it needs next." />
      {(backend || typeof tokensUsed === 'number' || approval) ? (
        <View style={styles.statusRow}>
          {backend ? <StatusPill label={backend} tone={backend === 'local' ? 'ok' : 'neutral'} /> : null}
          {typeof tokensUsed === 'number' ? <StatusPill label={`${tokensUsed} tokens`} tone="neutral" /> : null}
          {approval ? <StatusPill label="Approval needed" tone="warn" /> : null}
        </View>
      ) : null}
      {transcript ? (
        <View style={styles.block}>
          <Text style={[styles.label, { color: colors.muted }]}>Transcript</Text>
          <Text style={[styles.body, { color: colors.text }]}>{transcript}</Text>
        </View>
      ) : null}
      {response ? (
        <View style={styles.block}>
          <Text style={[styles.label, { color: colors.muted }]}>Response</Text>
          <Text style={[styles.body, { color: colors.text }]}>{response}</Text>
          {(onSpeak || onStopSpeaking) ? (
            <View style={styles.audioActions}>
              {onSpeak ? (
                <Pressable onPress={onSpeak} style={styles.audioButton}>
                  <Text style={styles.audioButtonText}>{speaking ? 'Replay' : 'Speak aloud'}</Text>
                </Pressable>
              ) : null}
              {speaking && onStopSpeaking ? (
                <Pressable onPress={onStopSpeaking} style={styles.audioButtonSecondary}>
                  <Text style={styles.audioButtonSecondaryText}>Stop</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}
      {approval ? (
        <View style={[styles.approvalCard, { borderColor: colors.warning }]}>
          <Text style={[styles.approvalTitle, { color: colors.text }]}>Axon is waiting on you</Text>
          <Text style={[styles.approvalBody, { color: colors.muted }]}>
            {approval.message || approval.resume_task || 'A protected action needs approval before Axon can continue.'}
          </Text>
          {onOpenSession ? (
            <Pressable onPress={onOpenSession} style={styles.approvalButton}>
              <Text style={styles.approvalButtonText}>Open session</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {error ? <Text style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  block: {
    gap: 6,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.7,
    textTransform: 'uppercase',
  },
  body: {
    fontSize: 14,
    lineHeight: 20,
  },
  approvalCard: {
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
    gap: 8,
    backgroundColor: '#1a1020',
  },
  approvalTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  approvalBody: {
    fontSize: 13,
    lineHeight: 18,
  },
  approvalButton: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  approvalButtonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  audioActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 6,
  },
  audioButton: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  audioButtonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  audioButtonSecondary: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  audioButtonSecondaryText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
  error: {
    fontSize: 12,
    lineHeight: 18,
  },
});
