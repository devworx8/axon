import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { AttentionItem, CompanionLiveSnapshot, CompanionSession, WorkspaceSummary } from '@/types/companion';
import { VoiceCommandComposer } from '@/features/voice/VoiceCommandComposer';
import { VoiceOutcomeCard } from '@/features/voice/VoiceOutcomeCard';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  linked: boolean;
  voiceMode: string;
  currentWorkspaceLabel?: string;
  liveSnapshot: CompanionLiveSnapshot | null;
  activeSession: CompanionSession | null;
  attentionCounts: Record<string, number>;
  workspaces: WorkspaceSummary[];
  lastTranscript?: string;
  responseText?: string;
  lastBackend?: string;
  lastTokens?: number;
  approvalMessage?: AttentionItem | null;
  approvalState?: {
    message?: string;
    resume_task?: string;
  } | null;
  error?: string | null;
  sending?: boolean;
  onSubmit: (text: string) => void;
  onOpenVoice: () => void;
  onOpenSession: () => void;
  onOpenWorkspace: () => void;
};

export function HomeScreen({
  linked,
  voiceMode,
  currentWorkspaceLabel,
  liveSnapshot,
  activeSession,
  attentionCounts,
  workspaces,
  lastTranscript,
  responseText,
  lastBackend,
  lastTokens,
  approvalState,
  error,
  sending,
  onSubmit,
  onOpenVoice,
  onOpenSession,
  onOpenWorkspace,
}: Props) {
  const { colors } = useTheme();
  const workspaceCount = workspaces.length;
  const operator = liveSnapshot?.operator || null;

  return (
    <View style={styles.stack}>
      <SurfaceCard>
        <Text style={[styles.kicker, { color: colors.accent }]}>Axon Voice Mode</Text>
        <Text style={[styles.title, { color: colors.text }]}>Your mobile command center</Text>
        <Text style={[styles.subtitle, { color: colors.muted }]}>
          Speak or type once, see what Axon is doing live, and jump straight into the next action.
        </Text>
        <View style={styles.statusRow}>
          <StatusPill label={linked ? 'Linked to live Axon' : 'Not linked'} tone={linked ? 'ok' : 'warn'} />
          <StatusPill label={voiceMode === 'live' ? 'Live voice mode' : 'Push-to-talk'} tone={voiceMode === 'live' ? 'accent' : 'neutral'} />
          {currentWorkspaceLabel ? <StatusPill label={currentWorkspaceLabel} tone="accent" /> : null}
        </View>
        <View style={styles.metrics}>
          <MetricCard label="Now" value={attentionCounts.now || 0} accent="warn" />
          <MetricCard label="Workspaces" value={workspaceCount} accent="accent" />
          <MetricCard label="Session" value={activeSession?.status || (operator?.active ? 'live' : 'idle')} accent={operator?.active ? 'success' : 'neutral'} />
        </View>
        <View style={styles.actionRow}>
          <Pressable onPress={onOpenVoice} style={styles.primaryAction}>
            <Text style={styles.primaryActionText}>Open voice</Text>
          </Pressable>
          <Pressable onPress={onOpenSession} style={styles.secondaryAction}>
            <Text style={styles.secondaryActionText}>Open session</Text>
          </Pressable>
          <Pressable onPress={onOpenWorkspace} style={styles.secondaryAction}>
            <Text style={styles.secondaryActionText}>Choose workspace</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <VoiceCommandComposer
        onSubmit={onSubmit}
        sending={sending}
        voiceMode={voiceMode}
        workspaceLabel={currentWorkspaceLabel}
        placeholder="Ask Axon to inspect code, explain status, or run a workspace action."
      />

      <VoiceOutcomeCard
        transcript={lastTranscript}
        response={responseText}
        backend={lastBackend}
        tokensUsed={lastTokens}
        approval={approvalState || undefined}
        error={error}
        onOpenSession={onOpenSession}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  kicker: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1.2,
  },
  title: {
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 20,
  },
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  primaryActionText: {
    color: '#08111f',
    fontWeight: '800',
  },
  secondaryAction: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  secondaryActionText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
});
