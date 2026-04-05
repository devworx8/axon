import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { AxonModeCard } from '@/features/axon/AxonModeCard';
import { MissionHeroCard } from './MissionHeroCard';
import { QuickActionsCard } from './QuickActionsCard';
import { VoiceCommandComposer } from '@/features/voice/VoiceCommandComposer';
import { VoiceOutcomeCard } from '@/features/voice/VoiceOutcomeCard';
import { ControlCapability, ExpoProjectStatus, PlatformSnapshot, TypedActionResult } from '@/types/companion';

export function MissionControlScreen({
  snapshot,
  digest,
  loading,
  sending,
  voiceMode,
  currentWorkspaceLabel,
  transcript,
  responseText,
  backend,
  tokensUsed,
  approval,
  capabilities,
  controlBusyActionType,
  lastAction,
  controlError,
  voiceError,
  speakingReply,
  expoProject,
  axonWakePhrase,
  onChangeAxonWakePhrase,
  axonBusy,
  axonError,
  onRefresh,
  onSubmitCommand,
  onExecuteAction,
  onApprovePending,
  onSpeakLatestReply,
  onStopSpeaking,
  onArmAxon,
  onDisarmAxon,
  onOpenVoice,
  onOpenAttention,
  onOpenProjects,
  onOpenSessions,
}: {
  snapshot: PlatformSnapshot | null;
  digest?: string;
  loading?: boolean;
  sending?: boolean;
  voiceMode?: string;
  currentWorkspaceLabel?: string;
  transcript?: string;
  responseText?: string;
  backend?: string;
  tokensUsed?: number;
  approval?: { message?: string; resume_task?: string } | null;
  capabilities?: ControlCapability[];
  controlBusyActionType?: string | null;
  lastAction?: TypedActionResult | null;
  controlError?: string | null;
  voiceError?: string | null;
  speakingReply?: boolean;
  expoProject?: ExpoProjectStatus | null;
  axonWakePhrase: string;
  onChangeAxonWakePhrase: (value: string) => void;
  axonBusy?: boolean;
  axonError?: string | null;
  onRefresh?: () => void;
  onSubmitCommand: (text: string) => void;
  onExecuteAction: (actionType: string) => void;
  onApprovePending: () => void;
  onSpeakLatestReply?: () => void;
  onStopSpeaking?: () => void;
  onArmAxon?: () => void;
  onDisarmAxon?: () => void;
  onOpenVoice: () => void;
  onOpenAttention: () => void;
  onOpenProjects: () => void;
  onOpenSessions: () => void;
}) {
  const latestOutcomeSummary = lastAction?.receipt?.summary || snapshot?.latest_command_outcome?.summary;

  return (
    <View style={styles.stack}>
      <MissionHeroCard snapshot={snapshot} digest={digest} loading={loading} onRefresh={onRefresh} />
      <QuickActionsCard
        quickActions={snapshot?.quick_actions}
        capabilities={capabilities}
        busyActionType={controlBusyActionType}
        onExecuteAction={onExecuteAction}
        onApprovePending={onApprovePending}
        onOpenVoice={onOpenVoice}
        onOpenProjects={onOpenProjects}
        onOpenAttention={onOpenAttention}
        onOpenSessions={onOpenSessions}
      />
      <SurfaceCard>
        <SurfaceHeader title="Voice control" subtitle="Push-to-talk or live listening stays ready in the cockpit." />
        <VoiceCommandComposer
          onSubmit={onSubmitCommand}
          sending={sending}
          voiceMode={voiceMode}
          workspaceLabel={currentWorkspaceLabel}
          placeholder="Tell Axon what needs to happen across the platform."
          prompts={[
            'What needs attention right now?',
            'Inspect the focused workspace.',
            'Sync all connector signals.',
          ]}
        />
      </SurfaceCard>
      <VoiceOutcomeCard
        transcript={transcript}
        response={responseText || latestOutcomeSummary}
        backend={backend || (lastAction?.result ? 'action' : undefined)}
        tokensUsed={tokensUsed}
        approval={approval}
        error={voiceError || controlError}
        onOpenSession={onOpenSessions}
        speaking={speakingReply}
        onSpeak={onSpeakLatestReply}
        onStopSpeaking={onStopSpeaking}
      />
      <AxonModeCard
        axon={snapshot?.axon}
        wakePhrase={axonWakePhrase}
        onChangeWakePhrase={onChangeAxonWakePhrase}
        busy={axonBusy}
        error={axonError}
        onArm={onArmAxon}
        onDisarm={onDisarmAxon}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  splitGroup: {
    gap: 16,
  },
  splitColumn: {
    gap: 14,
  },
});
