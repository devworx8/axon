import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { armAxonMode, disarmAxonMode, fetchAxonStatus, sendAxonEvent } from '@/api/axon';
import type {
  AxonModeStatus,
  CompanionConfig,
} from '@/types/companion';
import { isVoiceTranscriptionReady } from '@/features/voice/voiceReadiness';
import { useAxonBootSound } from './useAxonBootSound';
import { detectWakePhrase, isNoSpeechTranscriptError } from './voiceCommandUtils';

const AXON_LISTEN_WINDOW_MS = 4200;
const AXON_FOLLOW_UP_LISTEN_WINDOW_MS = 5200;
const AXON_FOLLOW_UP_COMMAND_WINDOW_MS = 8000;

type CaptureRuntime = {
  isRecording?: boolean;
  transcribing?: boolean;
  error?: string | null;
  startRecording: () => Promise<void>;
  stopRecordingToTranscript: () => Promise<{ transcript: string; engine: string; language: string }>;
  cancelRecording: () => Promise<void>;
};

type AxonSettings = {
  voiceEnabled: boolean;
  axonModeEnabled: boolean;
  axonWakePhrase: string;
  axonBootSound: boolean;
  spokenReplies: boolean;
  continuousForegroundMonitoring: boolean;
  axonVoiceProvider: string;
  axonVoiceIdentity: string;
};

function mergedStatus(snapshot: AxonModeStatus | null, current: AxonModeStatus | null): AxonModeStatus | null {
  if (!snapshot) {
    return current;
  }
  return {
    ...snapshot,
    monitoring_state: current?.monitoring_state || snapshot.monitoring_state,
    last_error: current?.last_error || snapshot.last_error,
  };
}

function normaliseWakePhrase(value: string) {
  return value.trim() || 'Axon';
}

export function useAxonMode(
  config: CompanionConfig,
  settings: AxonSettings,
  snapshot: AxonModeStatus | null,
  capture: CaptureRuntime,
  submitVoiceTurn: (content: string, transcript?: string, voiceMode?: string) => Promise<unknown>,
) {
  const [status, setStatus] = useState<AxonModeStatus | null>(snapshot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const appState = useRef<AppStateStatus>(AppState.currentState);
  const loopTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loopCancelled = useRef(false);
  const followUpCommandUntil = useRef(0);
  const bootSound = useAxonBootSound(Boolean(settings.axonBootSound));

  const effectiveStatus = useMemo(
    () => mergedStatus(snapshot, status),
    [snapshot, status],
  );
  const transcriptionReady = useMemo(
    () => isVoiceTranscriptionReady(effectiveStatus),
    [
      effectiveStatus?.cloud_transcription_available,
      effectiveStatus?.local_voice_ready,
      effectiveStatus?.transcription_ready,
    ],
  );

  const refresh = useCallback(async () => {
    if (!config.accessToken) {
      setStatus(null);
      return null;
    }
    try {
      const next = await fetchAxonStatus(config);
      setStatus(next.axon || null);
      setError(null);
      return next.axon || null;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to read Axon mode');
      throw nextError;
    }
  }, [config]);

  const pushEvent = useCallback(async (
    event_type: string,
    payload: Record<string, unknown> = {},
  ) => {
    if (!config.accessToken) {
      return null;
    }
    const next = await sendAxonEvent({
      event_type,
      workspace_id: config.workspaceId ?? null,
      session_id: config.sessionId ?? null,
      active_route: '/voice',
      app_state: appState.current,
      ...payload,
    }, config);
    setStatus(next.axon || null);
    return next;
  }, [config]);

  const arm = useCallback(async () => {
    if (!config.accessToken) {
      return null;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await armAxonMode({
        workspace_id: config.workspaceId ?? null,
        session_id: config.sessionId ?? null,
        wake_phrase: normaliseWakePhrase(settings.axonWakePhrase),
        boot_sound_enabled: Boolean(settings.axonBootSound),
        spoken_reply_enabled: Boolean(settings.spokenReplies),
        continuous_monitoring_enabled: Boolean(settings.continuousForegroundMonitoring),
        voice_provider_preference: String(settings.axonVoiceProvider || 'cloud'),
        voice_identity_preference: String(settings.axonVoiceIdentity || ''),
        active_route: '/voice',
        app_state: appState.current,
      }, config);
      setStatus(next.axon || null);
      const played = await bootSound.play();
      if (played) {
        pushEvent('boot_sound_played').catch(() => undefined);
      }
      return next.axon || null;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to arm Axon mode');
      throw nextError;
    } finally {
      setBusy(false);
    }
  }, [bootSound, config, pushEvent, settings.axonBootSound, settings.axonVoiceIdentity, settings.axonVoiceProvider, settings.axonWakePhrase, settings.continuousForegroundMonitoring, settings.spokenReplies]);

  const disarm = useCallback(async () => {
    if (!config.accessToken) {
      return null;
    }
    setBusy(true);
    setError(null);
    followUpCommandUntil.current = 0;
    try {
      if (capture.isRecording) {
        await capture.cancelRecording().catch(() => undefined);
      }
      const next = await disarmAxonMode({
        workspace_id: config.workspaceId ?? null,
        session_id: config.sessionId ?? null,
        active_route: '/voice',
        app_state: appState.current,
      }, config);
      setStatus(next.axon || null);
      return next.axon || null;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to disarm Axon mode');
      throw nextError;
    } finally {
      setBusy(false);
    }
  }, [capture, config]);

  useEffect(() => {
    setStatus(current => mergedStatus(snapshot, current));
  }, [snapshot]);

  useEffect(() => {
    if (!effectiveStatus?.armed) {
      followUpCommandUntil.current = 0;
    }
  }, [effectiveStatus?.armed]);

  useEffect(() => {
    if (!config.accessToken) {
      followUpCommandUntil.current = 0;
      setStatus(null);
      return;
    }
    refresh().catch(() => undefined);
  }, [config.accessToken, refresh]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      const previous = appState.current;
      appState.current = nextState;
      if (!effectiveStatus?.armed || previous === nextState) {
        return;
      }
      if (nextState !== 'active') {
        followUpCommandUntil.current = 0;
        setStatus(current => current ? {
          ...current,
          monitoring_state: 'degraded',
          app_state: nextState,
          degraded_reason: 'App left the foreground, so Axon mode paused.',
          last_error: 'App left the foreground, so Axon mode paused.',
        } : current);
        pushEvent('backgrounded', { error: 'App left the foreground, so Axon mode paused.' }).catch(() => undefined);
      } else {
        setStatus(current => current ? {
          ...current,
          monitoring_state: 'armed',
          app_state: 'foreground',
          degraded_reason: '',
          last_error: '',
        } : current);
        pushEvent('foregrounded').catch(() => undefined);
      }
    });
    return () => {
      subscription.remove();
    };
  }, [effectiveStatus?.armed, pushEvent]);

  useEffect(() => {
    loopCancelled.current = false;
    if (loopTimer.current) {
      clearTimeout(loopTimer.current);
      loopTimer.current = null;
    }
    const shouldListen = Boolean(
      config.accessToken
      && settings.voiceEnabled
      && settings.axonModeEnabled
      && effectiveStatus?.armed
      && effectiveStatus?.continuous_monitoring_enabled
      && transcriptionReady
      && appState.current === 'active',
    );
    if (!shouldListen) {
      return () => {
        loopCancelled.current = true;
      };
    }

    const schedule = (delay = 600) => {
      if (loopCancelled.current) {
        return;
      }
      loopTimer.current = setTimeout(() => {
        cycle().catch(() => undefined);
      }, delay);
    };

    const cycle = async () => {
      if (loopCancelled.current) {
        return;
      }
      const awaitingFollowUp = followUpCommandUntil.current > Date.now();
      if (capture.isRecording || capture.transcribing) {
        schedule(awaitingFollowUp ? 220 : 400);
        return;
      }
      try {
        setError(null);
        setStatus(current => current ? {
          ...current,
          monitoring_state: awaitingFollowUp ? 'engaged' : 'listening',
          app_state: 'foreground',
          degraded_reason: '',
          last_error: '',
        } : current);
        await capture.startRecording();
        const captureWindowMs = awaitingFollowUp ? AXON_FOLLOW_UP_LISTEN_WINDOW_MS : AXON_LISTEN_WINDOW_MS;
        loopTimer.current = setTimeout(async () => {
          if (loopCancelled.current) {
            return;
          }
          try {
            const heard = await capture.stopRecordingToTranscript();
            const transcript = heard.transcript.trim();
            const wakePhrase = effectiveStatus?.wake_phrase || settings.axonWakePhrase;
            const waitingForFollowUp = followUpCommandUntil.current > Date.now();
            if (transcript) {
              const wake = detectWakePhrase(transcript, wakePhrase);
              if (wake.matched) {
                setStatus(current => current ? {
                  ...current,
                  monitoring_state: 'engaged',
                  last_transcript: transcript,
                  last_wake_at: new Date().toISOString(),
                  last_command_text: wake.command,
                  degraded_reason: '',
                  last_error: '',
                } : current);
                await pushEvent('wake_detected', {
                  transcript,
                  command_text: wake.command,
                  wake_phrase: wakePhrase,
                });
                if (wake.command) {
                  followUpCommandUntil.current = 0;
                  await submitVoiceTurn(wake.command, transcript, 'axon');
                  await pushEvent('command_submitted', {
                    transcript,
                    command_text: wake.command,
                  });
                } else {
                  followUpCommandUntil.current = Date.now() + AXON_FOLLOW_UP_COMMAND_WINDOW_MS;
                }
              } else if (waitingForFollowUp) {
                followUpCommandUntil.current = 0;
                setStatus(current => current ? {
                  ...current,
                  monitoring_state: 'engaged',
                  last_transcript: transcript,
                  last_command_text: transcript,
                  last_command_at: new Date().toISOString(),
                  degraded_reason: '',
                  last_error: '',
                } : current);
                await submitVoiceTurn(transcript, transcript, 'axon');
                await pushEvent('command_submitted', {
                  transcript,
                  command_text: transcript,
                });
              }
            }
            const stillWaitingForFollowUp = followUpCommandUntil.current > Date.now();
            setStatus(current => current ? {
              ...current,
              monitoring_state: stillWaitingForFollowUp ? 'engaged' : (current.armed ? 'armed' : 'idle'),
              app_state: 'foreground',
              degraded_reason: '',
              last_error: '',
            } : current);
          } catch (nextError) {
            const message = nextError instanceof Error ? nextError.message : 'Axon listening failed';
            if (isNoSpeechTranscriptError(nextError)) {
              const stillWaitingForFollowUp = followUpCommandUntil.current > Date.now();
              setStatus(current => current ? {
                ...current,
                monitoring_state: stillWaitingForFollowUp ? 'engaged' : (current.armed ? 'armed' : 'idle'),
                app_state: 'foreground',
                degraded_reason: '',
                last_error: '',
              } : current);
            } else {
              followUpCommandUntil.current = 0;
              setError(message);
              setStatus(current => current ? {
                ...current,
                monitoring_state: 'degraded',
                degraded_reason: message,
                last_error: message,
              } : current);
              await pushEvent('error', { error: message });
            }
          } finally {
            schedule(followUpCommandUntil.current > Date.now() ? 220 : 900);
          }
        }, captureWindowMs);
      } catch (nextError) {
        const message = nextError instanceof Error ? nextError.message : 'Axon could not start listening';
        followUpCommandUntil.current = 0;
        setError(message);
        setStatus(current => current ? {
          ...current,
          monitoring_state: 'degraded',
          degraded_reason: message,
          last_error: message,
        } : current);
        pushEvent('error', { error: message }).catch(() => undefined);
        schedule(1200);
      }
    };

    schedule(120);
    return () => {
      loopCancelled.current = true;
      if (loopTimer.current) {
        clearTimeout(loopTimer.current);
        loopTimer.current = null;
      }
    };
  }, [
    capture,
    config.accessToken,
    effectiveStatus?.armed,
    effectiveStatus?.continuous_monitoring_enabled,
    effectiveStatus?.wake_phrase,
    pushEvent,
    settings.axonModeEnabled,
    settings.axonWakePhrase,
    settings.voiceEnabled,
    submitVoiceTurn,
    transcriptionReady,
  ]);

  return {
    status: effectiveStatus,
    busy,
    error,
    refresh,
    arm,
    disarm,
    pushEvent,
  };
}
