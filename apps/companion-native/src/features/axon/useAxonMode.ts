import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { armAxonMode, disarmAxonMode, fetchAxonStatus, sendAxonEvent } from '@/api/axon';
import type {
  AxonModeStatus,
  CompanionConfig,
} from '@/types/companion';
import { useAxonBootSound } from './useAxonBootSound';

type CaptureRuntime = {
  voiceStatus?: { transcription_available?: boolean } | null;
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

function detectWakePhrase(transcript: string, wakePhrase: string) {
  const phrase = normaliseWakePhrase(wakePhrase).toLowerCase();
  const spoken = transcript.trim();
  const lowered = spoken.toLowerCase();
  if (lowered === phrase) {
    return { matched: true, command: '' };
  }
  if (lowered.startsWith(`${phrase} `)) {
    return { matched: true, command: spoken.slice(phrase.length).trim() };
  }
  return { matched: false, command: '' };
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
  const bootSound = useAxonBootSound(Boolean(settings.axonBootSound));

  const effectiveStatus = useMemo(
    () => mergedStatus(snapshot, status),
    [snapshot, status],
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
    if (!config.accessToken) {
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
      && effectiveStatus?.local_voice_ready
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
      if (capture.isRecording || capture.transcribing) {
        schedule(400);
        return;
      }
      try {
        setStatus(current => current ? { ...current, monitoring_state: 'listening', app_state: 'foreground' } : current);
        await capture.startRecording();
        loopTimer.current = setTimeout(async () => {
          try {
            const heard = await capture.stopRecordingToTranscript();
            const transcript = heard.transcript.trim();
            if (transcript) {
              const wake = detectWakePhrase(transcript, effectiveStatus?.wake_phrase || settings.axonWakePhrase);
              if (wake.matched) {
                setStatus(current => current ? {
                  ...current,
                  monitoring_state: 'engaged',
                  last_transcript: transcript,
                  last_wake_at: new Date().toISOString(),
                  last_command_text: wake.command,
                } : current);
                await pushEvent('wake_detected', {
                  transcript,
                  command_text: wake.command,
                  wake_phrase: effectiveStatus?.wake_phrase || settings.axonWakePhrase,
                });
                if (wake.command) {
                  await submitVoiceTurn(wake.command, transcript, 'axon');
                  await pushEvent('command_submitted', {
                    transcript,
                    command_text: wake.command,
                  });
                }
              }
            }
            setStatus(current => current ? {
              ...current,
              monitoring_state: current.armed ? 'armed' : 'idle',
              app_state: 'foreground',
            } : current);
          } catch (nextError) {
            const message = nextError instanceof Error ? nextError.message : 'Axon listening failed';
            setError(message);
            setStatus(current => current ? {
              ...current,
              monitoring_state: 'degraded',
              degraded_reason: message,
              last_error: message,
            } : current);
            await pushEvent('error', { error: message });
          } finally {
            schedule(900);
          }
        }, 2400);
      } catch (nextError) {
        const message = nextError instanceof Error ? nextError.message : 'Axon could not start listening';
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
    effectiveStatus?.local_voice_ready,
    effectiveStatus?.wake_phrase,
    pushEvent,
    settings.axonModeEnabled,
    settings.axonWakePhrase,
    settings.voiceEnabled,
    submitVoiceTurn,
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
