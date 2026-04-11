import React from 'react';

import { useLiveVoiceCapture } from '@/features/voice/useLiveVoiceCapture';
import { isVoiceTranscriptionReady } from '@/features/voice/voiceReadiness';
import { useVoiceAutomation } from '@/features/voice/useVoiceAutomation';
import type { CompanionConfig } from '@/types/companion-core';
import type { CompanionSettings } from '@/features/settings/useSettings';
import type { AxonModeStatus } from '@/types/axon';
import type { VoiceTurnResponse } from '@/types/companion-core';
import { useAxonMode } from './useAxonMode';
import { useAxonSpeech } from './useAxonSpeech';
import { buildSpeechRecognitionContext } from './voiceCommandUtils';

type AppTab = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

export function useAxonMobileRuntime({
  config,
  settings,
  missionAxonSnapshot,
  voice,
  syncMission,
  setActiveTab,
  activeTab,
}: {
  config: CompanionConfig;
  settings: CompanionSettings;
  missionAxonSnapshot: AxonModeStatus | null;
  voice: {
    submitVoiceTurn: (content: string, transcript?: string, voiceMode?: string) => Promise<VoiceTurnResponse>;
    sending?: boolean;
    error?: string | null;
    lastResult?: VoiceTurnResponse | null;
  };
  syncMission: () => Promise<unknown>;
  setActiveTab: (tab: AppTab) => void;
  activeTab: AppTab;
}) {
  const speech = useAxonSpeech(Boolean(settings.voiceEnabled && settings.spokenReplies), config, {
    axonVoiceProvider: settings.axonVoiceProvider,
    axonVoiceIdentity: settings.axonVoiceIdentity,
  });

  const handleVoiceSubmit = React.useCallback(async (text: string) => {
    if (!String(text || '').trim()) return;
    try {
      const result = await voice.submitVoiceTurn(
        text,
        text,
        settings.alwaysListening ? 'live' : 'push_to_talk',
      );
      syncMission().catch(() => {});
      if (result.approval_required) {
        setActiveTab('sessions');
        return;
      }
    } catch (err) {
      console.error('[Axon] Voice submission failed:', err);
      setActiveTab('voice');
    }
  }, [setActiveTab, settings.alwaysListening, syncMission, voice]);

  const liveVoice = useLiveVoiceCapture(config, {
    enabled: Boolean(settings.voiceEnabled),
    language: 'en',
    wakePhrase: settings.axonWakePhrase,
    contextualPhrases: buildSpeechRecognitionContext(settings.axonWakePhrase),
    autoSubmitOnSpeechEnd: Boolean(settings.alwaysListening),
    onTranscript: handleVoiceSubmit,
  });

  const submitAxonVoiceTurn = React.useCallback(async (content: string, transcript?: string, voiceMode?: string) => {
    const result = await voice.submitVoiceTurn(
      content,
      transcript,
      voiceMode || (settings.alwaysListening ? 'live' : 'push_to_talk'),
    );
    syncMission().catch(() => {});
    if (result.approval_required) {
      setActiveTab('sessions');
    }
    return result;
  }, [setActiveTab, settings.alwaysListening, syncMission, voice]);

  const axonMode = useAxonMode(
    config,
    settings,
    missionAxonSnapshot || null,
    {
      isRecording: liveVoice.isRecording,
      transcribing: liveVoice.transcribing,
      error: liveVoice.error,
      startRecording: liveVoice.startRecording,
      stopRecordingToTranscript: liveVoice.stopRecordingToTranscript,
      cancelRecording: liveVoice.cancelRecording,
    },
    submitAxonVoiceTurn,
  );

  const handleArmAxon = React.useCallback(async () => {
    await axonMode.arm();
    await syncMission();
  }, [axonMode, syncMission]);

  const handleDisarmAxon = React.useCallback(async () => {
    await axonMode.disarm();
    await syncMission();
  }, [axonMode, syncMission]);

  useVoiceAutomation({
    active: activeTab === 'voice',
    enabled: Boolean(settings.voiceEnabled),
    autoListen: Boolean(settings.alwaysListening),
    axonArmed: Boolean(axonMode.status?.armed),
    ready: Boolean(isVoiceTranscriptionReady(liveVoice.voiceStatus)),
    checkingStatus: Boolean(liveVoice.checkingStatus),
    recording: Boolean(liveVoice.isRecording),
    transcribing: Boolean(liveVoice.transcribing),
    sending: Boolean(voice.sending),
    speaking: Boolean(speech.speaking),
    approvalPending: Boolean(voice.lastResult?.approval_required),
    captureError: liveVoice.error || voice.error,
    refreshVoiceStatus: liveVoice.refreshVoiceStatus,
    startRecording: liveVoice.startRecording,
  });

  return {
    speech,
    liveVoice,
    axonMode,
    handleVoiceSubmit,
    handleArmAxon,
    handleDisarmAxon,
  };
}
