import React from 'react';

import { useLiveVoiceCapture } from '@/features/voice/useLiveVoiceCapture';
import type { CompanionConfig } from '@/types/companion-core';
import type { CompanionSettings } from '@/features/settings/useSettings';
import type { AxonModeStatus } from '@/types/axon';
import type { VoiceTurnResponse } from '@/types/companion-core';
import { useAxonMode } from './useAxonMode';
import { useAxonSpeech } from './useAxonSpeech';

type AppTab = 'home' | 'voice' | 'sessions' | 'mission' | 'settings';

export function useAxonMobileRuntime({
  config,
  settings,
  missionAxonSnapshot,
  voice,
  syncMission,
  setActiveTab,
}: {
  config: CompanionConfig;
  settings: CompanionSettings;
  missionAxonSnapshot: AxonModeStatus | null;
  voice: { submitVoiceTurn: (content: string, transcript?: string, voiceMode?: string) => Promise<VoiceTurnResponse> };
  syncMission: () => Promise<unknown>;
  setActiveTab: (tab: AppTab) => void;
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
      await syncMission();
      if (result.approval_required) {
        setActiveTab('sessions');
        return;
      }
      setActiveTab('mission');
    } catch (err) {
      console.error('[Axon] Voice submission failed:', err);
      setActiveTab('voice');
    }
  }, [setActiveTab, settings.alwaysListening, syncMission, voice]);

  const liveVoice = useLiveVoiceCapture(config, {
    enabled: Boolean(settings.voiceEnabled),
    language: 'en',
    onTranscript: handleVoiceSubmit,
  });

  const submitAxonVoiceTurn = React.useCallback(async (content: string, transcript?: string, voiceMode?: string) => {
    const result = await voice.submitVoiceTurn(
      content,
      transcript,
      voiceMode || (settings.alwaysListening ? 'live' : 'push_to_talk'),
    );
    await syncMission();
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
      voiceStatus: liveVoice.voiceStatus,
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

  return {
    speech,
    liveVoice,
    axonMode,
    handleVoiceSubmit,
    handleArmAxon,
    handleDisarmAxon,
  };
}
