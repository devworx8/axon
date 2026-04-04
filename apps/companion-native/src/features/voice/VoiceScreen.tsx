import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { AxonModeCard } from '@/features/axon/AxonModeCard';
import { ApprovalRequired } from '@/types/companion';
import { LocalVoiceStatus } from '@/types/companion';
import { AxonModeStatus } from '@/types/companion';
import { VoiceCaptureCard } from './VoiceCaptureCard';
import { VoiceCommandComposer } from './VoiceCommandComposer';
import { VoiceOutcomeCard } from './VoiceOutcomeCard';

type Props = {
  onSubmit: (text: string) => void;
  sending?: boolean;
  transcript?: string;
  response?: string;
  backend?: string;
  tokensUsed?: number;
  approval?: ApprovalRequired | null;
  voiceMode?: string;
  error?: string | null;
  workspaceLabel?: string;
  onOpenSession?: () => void;
  speaking?: boolean;
  onSpeak?: () => void;
  onStopSpeaking?: () => void;
  liveVoiceStatus?: LocalVoiceStatus | null;
  checkingVoiceStatus?: boolean;
  recording?: boolean;
  transcribing?: boolean;
  recordingDuration?: string;
  liveTranscript?: string;
  liveEngine?: string;
  liveError?: string | null;
  onStartLiveVoice?: () => void;
  onStopLiveVoice?: () => void;
  onRefreshLiveVoice?: () => void;
  axon?: AxonModeStatus | null;
  axonWakePhrase: string;
  onChangeAxonWakePhrase: (value: string) => void;
  axonBusy?: boolean;
  axonError?: string | null;
  onArmAxon?: () => void;
  onDisarmAxon?: () => void;
};

export function VoiceScreen({
  onSubmit,
  sending,
  transcript,
  response,
  backend,
  tokensUsed,
  approval,
  voiceMode,
  error,
  workspaceLabel,
  onOpenSession,
  speaking,
  onSpeak,
  onStopSpeaking,
  liveVoiceStatus,
  checkingVoiceStatus,
  recording,
  transcribing,
  recordingDuration,
  liveTranscript,
  liveEngine,
  liveError,
  onStartLiveVoice,
  onStopLiveVoice,
  onRefreshLiveVoice,
  axon,
  axonWakePhrase,
  onChangeAxonWakePhrase,
  axonBusy,
  axonError,
  onArmAxon,
  onDisarmAxon,
}: Props) {

  return (
    <View style={styles.stack}>
      <AxonModeCard
        axon={axon}
        wakePhrase={axonWakePhrase}
        onChangeWakePhrase={onChangeAxonWakePhrase}
        busy={axonBusy}
        error={axonError}
        onArm={onArmAxon}
        onDisarm={onDisarmAxon}
      />
      <VoiceCaptureCard
        voiceStatus={liveVoiceStatus}
        checkingStatus={checkingVoiceStatus}
        isRecording={recording}
        transcribing={transcribing}
        durationLabel={recordingDuration}
        transcript={liveTranscript}
        engine={liveEngine}
        error={liveError}
        onStart={onStartLiveVoice}
        onStop={onStopLiveVoice}
        onRefresh={onRefreshLiveVoice}
      />
      <SurfaceCard>
        <SurfaceHeader title="Axon Voice Mode" subtitle="Run a command fast, then let Axon route it to the right workspace or approval flow." />
        <Text style={styles.helper}>Typed fallback stays available even when live capture is unavailable, muted, or not the fastest path.</Text>
        <VoiceCommandComposer
          onSubmit={onSubmit}
          sending={sending}
          voiceMode={voiceMode}
          workspaceLabel={workspaceLabel}
          placeholder="Ask Axon what changed, what needs attention, or what to do next."
          prompts={[
            'What needs attention right now?',
            'What is the workspace path?',
            'Inspect the active workspace and tell me what matters.',
          ]}
        />
      </SurfaceCard>
      <VoiceOutcomeCard
        transcript={transcript}
        response={response}
        backend={backend}
        tokensUsed={tokensUsed}
        approval={approval}
        error={error}
        onOpenSession={onOpenSession}
        speaking={speaking}
        onSpeak={onSpeak}
        onStopSpeaking={onStopSpeaking}
      />
      {approval?.resume_task ? (
        <SurfaceCard>
          <SurfaceHeader title="Next step" subtitle="Axon already knows what comes after approval." />
          <Text style={styles.nextStep}>{approval.resume_task}</Text>
        </SurfaceCard>
      ) : null}
      {!transcript && !response && !approval && !error ? (
        <SurfaceCard>
          <SurfaceHeader title="What works today" subtitle="Use live capture or typed commands to drive the same Axon mobile control path." />
          <Text style={styles.nextStep}>Use this screen to record a command, type a fallback prompt, retrieve workspace facts with zero tokens on fast paths, and escalate protected actions into a resumable mobile session.</Text>
        </SurfaceCard>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  helper: {
    color: '#94a3b8',
    fontSize: 13,
    lineHeight: 18,
  },
  nextStep: {
    color: '#e5eefb',
    fontSize: 14,
    lineHeight: 20,
  },
});
