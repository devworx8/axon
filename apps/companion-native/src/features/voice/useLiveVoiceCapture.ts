import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';

import { fetchVoiceStatus, transcribeRecordedAudio } from '@/api/voice';
import { CompanionConfig, LocalVoiceStatus } from '@/types/companion';

function buildRecordingFilename(uri: string, mimeType: string) {
  const cleanMime = String(mimeType || 'audio/webm').toLowerCase();
  if (cleanMime.includes('mpeg') || cleanMime.includes('mp3')) return 'voice.mp3';
  if (cleanMime.includes('mp4') || cleanMime.includes('aac')) return 'voice.m4a';
  if (cleanMime.includes('wav')) return 'voice.wav';
  if (cleanMime.includes('ogg')) return 'voice.ogg';
  if (cleanMime.includes('webm')) return 'voice.webm';
  const suffix = uri.split('.').pop()?.trim();
  return suffix ? `voice.${suffix}` : 'voice.webm';
}

export function useLiveVoiceCapture(
  config: CompanionConfig,
  options: {
    enabled: boolean;
    language: string;
    onTranscript: (text: string) => Promise<void> | void;
  },
) {
  const { enabled, language, onTranscript } = options;
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 250);
  const [voiceStatus, setVoiceStatus] = useState<LocalVoiceStatus | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState('');
  const [lastEngine, setLastEngine] = useState('');
  const startingRef = useRef(false);

  const refreshVoiceStatus = useCallback(async () => {
    setCheckingStatus(true);
    try {
      const status = await fetchVoiceStatus(config);
      setVoiceStatus(status);
      return status;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to read Axon voice status');
      throw err;
    } finally {
      setCheckingStatus(false);
    }
  }, [config]);

  useEffect(() => {
    refreshVoiceStatus().catch(() => undefined);
  }, [refreshVoiceStatus]);

  useEffect(() => {
    if (!enabled && recorderState.isRecording) {
      recorder.stop().catch(() => undefined);
    }
  }, [enabled, recorder, recorderState.isRecording]);

  const durationLabel = useMemo(() => {
    const totalSeconds = Math.max(0, Math.round((recorderState.durationMillis || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }, [recorderState.durationMillis]);

  const startRecording = useCallback(async () => {
    if (startingRef.current) return;
    setError(null);
    const status = voiceStatus || await refreshVoiceStatus();
    if (!enabled) {
      throw new Error('Voice is disabled in settings.');
    }
    if (!(status?.transcription_ready || status?.transcription_available)) {
      throw new Error(status?.detail || 'No transcription backend available (local or cloud).');
    }
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      throw new Error('Microphone permission was denied.');
    }
    if (recorderState.isRecording) {
      return;
    }
    startingRef.current = true;
    try {
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
      });
      if (!recorderState.canRecord) {
        await recorder.prepareToRecordAsync();
      }
      recorder.record();
    } finally {
      startingRef.current = false;
    }
  }, [enabled, recorder, recorderState.canRecord, recorderState.isRecording, refreshVoiceStatus, voiceStatus]);

  const stopRecordingToTranscript = useCallback(async () => {
    if (!recorderState.isRecording) {
      throw new Error('No live recording is active to stop.');
    }
    await recorder.stop();
    await setAudioModeAsync({
      allowsRecording: false,
      playsInSilentMode: true,
    });
    const uri = recorder.uri || recorderState.url || '';
    if (!uri) {
      throw new Error('Recording finished but no audio file was produced.');
    }
    const mimeType = uri.endsWith('.m4a')
      ? 'audio/mp4'
      : uri.endsWith('.wav')
        ? 'audio/wav'
        : uri.endsWith('.ogg')
          ? 'audio/ogg'
          : 'audio/webm';
    const transcriptResult = await transcribeRecordedAudio(uri, {
      language,
      mimeType,
      filename: buildRecordingFilename(uri, mimeType),
      config,
    });
    const transcript = String(transcriptResult.text || '').trim();
    if (!transcript) {
      throw new Error('Axon could not detect speech in that recording.');
    }
    setLastTranscript(transcript);
    setLastEngine(String(transcriptResult.engine || ''));
    return {
      transcript,
      engine: String(transcriptResult.engine || ''),
      language: String(transcriptResult.language || language),
    };
  }, [config, language, recorder, recorderState.url]);

  const stopAndSubmit = useCallback(async () => {
    setError(null);
    setTranscribing(true);
    try {
      const result = await stopRecordingToTranscript();
      const transcript = result.transcript;
      await onTranscript(transcript);
      return transcript;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice capture failed');
      throw err;
    } finally {
      setTranscribing(false);
    }
  }, [onTranscript, stopRecordingToTranscript]);

  const cancelRecording = useCallback(async () => {
    setError(null);
    if (!recorderState.isRecording) {
      return;
    }
    await recorder.stop();
    await setAudioModeAsync({
      allowsRecording: false,
      playsInSilentMode: true,
    });
  }, [recorder, recorderState.isRecording]);

  return {
    voiceStatus,
    checkingStatus,
    transcribing,
    error,
    setError,
    lastTranscript,
    lastEngine,
    isRecording: Boolean(recorderState.isRecording),
    durationLabel,
    canUseLiveVoice: Boolean(enabled && (voiceStatus?.transcription_ready || voiceStatus?.transcription_available)),
    refreshVoiceStatus,
    startRecording,
    stopRecordingToTranscript,
    stopAndSubmit,
    cancelRecording,
  };
}
