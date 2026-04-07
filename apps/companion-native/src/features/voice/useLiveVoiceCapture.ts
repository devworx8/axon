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
import { isVoiceTranscriptionReady } from './voiceReadiness';
import { useLiveSpeechRecognition } from './useLiveSpeechRecognition';

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

function inferMimeType(uri: string) {
  const lower = String(uri || '').toLowerCase();
  if (lower.endsWith('.m4a') || lower.endsWith('.mp4') || lower.endsWith('.aac')) return 'audio/mp4';
  if (lower.endsWith('.wav')) return 'audio/wav';
  if (lower.endsWith('.ogg')) return 'audio/ogg';
  if (lower.endsWith('.caf')) return 'audio/x-caf';
  return 'audio/webm';
}

function formatDurationLabel(durationMillis: number) {
  const totalSeconds = Math.max(0, Math.round((durationMillis || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function useLiveVoiceCapture(
  config: CompanionConfig,
  options: {
    enabled: boolean;
    language: string;
    autoSubmitOnSpeechEnd?: boolean;
    onTranscript: (text: string) => Promise<void> | void;
  },
) {
  const { enabled, language, autoSubmitOnSpeechEnd = false, onTranscript } = options;
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 250);
  const recorderStateRef = useRef(recorderState);
  const liveSpeech = useLiveSpeechRecognition({ enabled, language });
  const [voiceStatus, setVoiceStatus] = useState<LocalVoiceStatus | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState('');
  const [lastEngine, setLastEngine] = useState('');
  const startingRef = useRef(false);
  const autoSubmittingRef = useRef(false);

  const refreshVoiceStatus = useCallback(async () => {
    setCheckingStatus(true);
    try {
      const status = await fetchVoiceStatus(config);
      setVoiceStatus(status);
      setError(null);
      return status;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to read Axon voice status');
      throw err;
    } finally {
      setCheckingStatus(false);
    }
  }, [config]);

  useEffect(() => {
    recorderStateRef.current = recorderState;
  }, [recorderState]);

  useEffect(() => {
    const interimTranscript = String(
      liveSpeech.finalTranscript
      || liveSpeech.interimTranscript
      || liveSpeech.transcript
      || '',
    ).trim();
    if (liveSpeech.listening && interimTranscript) {
      setLastTranscript(interimTranscript);
      setLastEngine('device-live');
    }
  }, [
    liveSpeech.finalTranscript,
    liveSpeech.interimTranscript,
    liveSpeech.listening,
    liveSpeech.transcript,
  ]);

  useEffect(() => {
    refreshVoiceStatus().catch(() => undefined);
  }, [refreshVoiceStatus]);

  useEffect(() => {
    if (!enabled && recorderState.isRecording) {
      recorder.stop().catch(() => undefined);
    }
    if (!enabled && liveSpeech.listening) {
      liveSpeech.abortListening().catch(() => undefined);
    }
  }, [enabled, liveSpeech, recorder, recorderState.isRecording]);

  const durationLabel = useMemo(() => {
    if (liveSpeech.listening || liveSpeech.durationMillis > 0) {
      return formatDurationLabel(liveSpeech.durationMillis);
    }
    return formatDurationLabel(recorderState.durationMillis || 0);
  }, [liveSpeech.durationMillis, liveSpeech.listening, recorderState.durationMillis]);

  const startRecording = useCallback(async () => {
    if (startingRef.current) return;
    try {
      setError(null);
      setLastTranscript('');
      setLastEngine('');
      const status = await refreshVoiceStatus();
      if (!enabled) {
        throw new Error('Voice is disabled in settings.');
      }
      if (!isVoiceTranscriptionReady(status)) {
        throw new Error(status?.detail || 'No transcription backend available (local or cloud).');
      }
      liveSpeech.resetTranscript();
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) {
        throw new Error('Microphone permission was denied.');
      }
      if (liveSpeech.available) {
        startingRef.current = true;
        await liveSpeech.startListening();
        return;
      }
      if (recorderState.isRecording) {
        return;
      }
      startingRef.current = true;
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
      });
      if (!recorderState.canRecord) {
        await recorder.prepareToRecordAsync();
      }
      recorder.record();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice capture could not start');
      throw err;
    } finally {
      startingRef.current = false;
    }
  }, [
    enabled,
    liveSpeech,
    recorder,
    recorderState.canRecord,
    recorderState.isRecording,
    refreshVoiceStatus,
  ]);

  const stopSpeechRecognitionToTranscript = useCallback(async () => {
    const snapshot = liveSpeech.listening
      ? await liveSpeech.stopListening()
      : liveSpeech.currentSnapshot();
    const liveTranscript = String(
      snapshot.finalTranscript
      || snapshot.interimTranscript
      || snapshot.transcript
      || '',
    ).trim();
    const audioUri = String(snapshot.audioUri || '').trim();
    if (audioUri) {
      const mimeType = inferMimeType(audioUri);
      const transcriptResult = await transcribeRecordedAudio(audioUri, {
        language,
        mimeType,
        filename: buildRecordingFilename(audioUri, mimeType),
        config,
      });
      const transcript = String(transcriptResult.text || liveTranscript).trim();
      if (!transcript) {
        throw new Error('Axon could not detect speech in that recording.');
      }
      const engine = String(transcriptResult.engine || (liveTranscript ? 'device-live' : '')).trim();
      setLastTranscript(transcript);
      setLastEngine(engine);
      return {
        transcript,
        engine,
        language: String(transcriptResult.language || language),
      };
    }
    if (liveTranscript) {
      setLastTranscript(liveTranscript);
      setLastEngine('device-live');
      return {
        transcript: liveTranscript,
        engine: 'device-live',
        language,
      };
    }
    throw new Error(snapshot.error || 'Axon could not detect speech in that recording.');
  }, [config, language, liveSpeech]);

  const stopRecordingToTranscript = useCallback(async () => {
    const hasSpeechRecognitionCapture = Boolean(
      liveSpeech.available
      && (
        liveSpeech.listening
        || liveSpeech.audioUri
        || liveSpeech.finalTranscript
        || liveSpeech.interimTranscript
        || liveSpeech.transcript
      ),
    );
    if (hasSpeechRecognitionCapture) {
      return stopSpeechRecognitionToTranscript();
    }
    const currentState = recorderStateRef.current;
    if (!currentState.isRecording) {
      throw new Error('No live recording is active to stop.');
    }
    await recorder.stop();
    await setAudioModeAsync({
      allowsRecording: false,
      playsInSilentMode: true,
    });
    const uri = recorder.uri || recorderStateRef.current.url || currentState.url || '';
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
  }, [
    config,
    language,
    liveSpeech.audioUri,
    liveSpeech.available,
    liveSpeech.finalTranscript,
    liveSpeech.interimTranscript,
    liveSpeech.listening,
    liveSpeech.transcript,
    recorder,
    stopSpeechRecognitionToTranscript,
  ]);

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
    if (liveSpeech.listening) {
      await liveSpeech.abortListening();
      return;
    }
    if (!recorderState.isRecording) {
      return;
    }
    await recorder.stop();
    await setAudioModeAsync({
      allowsRecording: false,
      playsInSilentMode: true,
    });
  }, [liveSpeech, recorder, recorderState.isRecording]);

  useEffect(() => {
    if (!autoSubmitOnSpeechEnd || !enabled || !liveSpeech.naturalCompletionToken) {
      return;
    }
    const transcript = String(
      liveSpeech.finalTranscript
      || liveSpeech.interimTranscript
      || liveSpeech.transcript
      || '',
    ).trim();
    if (!transcript || autoSubmittingRef.current || transcribing) {
      return;
    }
    autoSubmittingRef.current = true;
    stopAndSubmit()
      .catch(() => undefined)
      .finally(() => {
        autoSubmittingRef.current = false;
      });
  }, [
    autoSubmitOnSpeechEnd,
    enabled,
    liveSpeech.finalTranscript,
    liveSpeech.interimTranscript,
    liveSpeech.naturalCompletionToken,
    liveSpeech.transcript,
    stopAndSubmit,
    transcribing,
  ]);

  return {
    voiceStatus,
    checkingStatus,
    transcribing,
    error,
    setError,
    lastTranscript,
    lastEngine,
    isRecording: Boolean(liveSpeech.listening || recorderState.isRecording),
    durationLabel,
    canUseLiveVoice: Boolean(enabled && isVoiceTranscriptionReady(voiceStatus)),
    refreshVoiceStatus,
    startRecording,
    stopRecordingToTranscript,
    stopAndSubmit,
    cancelRecording,
  };
}
