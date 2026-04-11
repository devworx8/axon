import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ExpoSpeechRecognitionModule,
  useSpeechRecognitionEvent,
  type ExpoSpeechRecognitionErrorEvent,
  type ExpoSpeechRecognitionResultEvent,
} from 'expo-speech-recognition';
import {
  buildSpeechRecognitionContext,
  canonicalizeWakePhraseTranscript,
} from '@/features/axon/voiceCommandUtils';

type RecognitionSnapshot = {
  sessionId: number;
  transcript: string;
  interimTranscript: string;
  finalTranscript: string;
  audioUri: string;
  heardSpeech: boolean;
  error: string | null;
};

type PendingStop = {
  resolve: (value: RecognitionSnapshot) => void;
  timeout: ReturnType<typeof setTimeout>;
};

function readTranscript(event: ExpoSpeechRecognitionResultEvent, wakePhrase: string): string {
  return canonicalizeWakePhraseTranscript(
    String(event.results?.[0]?.transcript || '').trim(),
    wakePhrase,
  );
}

function formatError(event: ExpoSpeechRecognitionErrorEvent): string | null {
  const code = String(event.error || '').trim().toLowerCase();
  if (!code || code === 'aborted' || code === 'no-speech' || code === 'speech-timeout') {
    return null;
  }
  return String(event.message || 'Speech recognition failed.').trim() || 'Speech recognition failed.';
}

function buildSnapshot(state: RecognitionSnapshot): RecognitionSnapshot {
  const transcript = String(
    state.finalTranscript
    || state.interimTranscript
    || state.transcript
    || '',
  ).trim();
  return {
    ...state,
    transcript,
    interimTranscript: String(state.interimTranscript || '').trim(),
    finalTranscript: String(state.finalTranscript || '').trim(),
    audioUri: String(state.audioUri || '').trim(),
    error: state.error ? String(state.error).trim() : null,
  };
}

export function useLiveSpeechRecognition({
  enabled,
  language,
  wakePhrase = 'Axon',
  contextualStrings = [],
}: {
  enabled: boolean;
  language: string;
  wakePhrase?: string;
  contextualStrings?: string[];
}) {
  const [available, setAvailable] = useState(false);
  const [supportsRecording, setSupportsRecording] = useState(false);
  const [listening, setListening] = useState(false);
  const [durationMillis, setDurationMillis] = useState(0);
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [finalTranscript, setFinalTranscript] = useState('');
  const [audioUri, setAudioUri] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [naturalCompletionToken, setNaturalCompletionToken] = useState(0);

  const sessionRef = useRef<RecognitionSnapshot & { startedAt: number }>({
    sessionId: 0,
    transcript: '',
    interimTranscript: '',
    finalTranscript: '',
    audioUri: '',
    heardSpeech: false,
    error: null,
    startedAt: 0,
  });
  const pendingStopRef = useRef<PendingStop | null>(null);
  const manualStopRef = useRef(false);

  const syncAvailability = useCallback(() => {
    if (!enabled) {
      setAvailable(false);
      setSupportsRecording(false);
      return;
    }
    try {
      setAvailable(Boolean(ExpoSpeechRecognitionModule.isRecognitionAvailable()));
      setSupportsRecording(Boolean(ExpoSpeechRecognitionModule.supportsRecording()));
    } catch {
      setAvailable(false);
      setSupportsRecording(false);
    }
  }, [enabled]);

  const resolvePendingStop = useCallback(() => {
    const pending = pendingStopRef.current;
    if (!pending) {
      return;
    }
    pendingStopRef.current = null;
    clearTimeout(pending.timeout);
    pending.resolve(buildSnapshot(sessionRef.current));
  }, []);

  const resetSessionState = useCallback((sessionId: number) => {
    const nextState = {
      sessionId,
      transcript: '',
      interimTranscript: '',
      finalTranscript: '',
      audioUri: '',
      heardSpeech: false,
      error: null,
      startedAt: 0,
    };
    sessionRef.current = nextState;
    setTranscript('');
    setInterimTranscript('');
    setFinalTranscript('');
    setAudioUri('');
    setError(null);
    setDurationMillis(0);
  }, []);

  useEffect(() => {
    syncAvailability();
  }, [syncAvailability]);

  useEffect(() => {
    if (!listening) {
      setDurationMillis(0);
      return;
    }
    const timer = setInterval(() => {
      const startedAt = sessionRef.current.startedAt || Date.now();
      setDurationMillis(Math.max(0, Date.now() - startedAt));
    }, 250);
    return () => clearInterval(timer);
  }, [listening]);

  useSpeechRecognitionEvent('start', () => {
    sessionRef.current.startedAt = Date.now();
    setListening(true);
    setError(null);
  });

  useSpeechRecognitionEvent('result', (event) => {
    const nextTranscript = readTranscript(event, wakePhrase);
    if (!nextTranscript) {
      return;
    }
    sessionRef.current.heardSpeech = true;
    sessionRef.current.transcript = nextTranscript;
    setTranscript(nextTranscript);
    if (event.isFinal) {
      sessionRef.current.finalTranscript = nextTranscript;
      sessionRef.current.interimTranscript = '';
      setFinalTranscript(nextTranscript);
      setInterimTranscript('');
    } else {
      sessionRef.current.interimTranscript = nextTranscript;
      setInterimTranscript(nextTranscript);
    }
  });

  useSpeechRecognitionEvent('audioend', (event) => {
    const nextUri = String(event?.uri || '').trim();
    sessionRef.current.audioUri = nextUri;
    setAudioUri(nextUri);
  });

  useSpeechRecognitionEvent('error', (event) => {
    const nextError = formatError(event);
    sessionRef.current.error = nextError;
    setError(nextError);
  });

  useSpeechRecognitionEvent('end', () => {
    const wasManualStop = manualStopRef.current;
    manualStopRef.current = false;
    setListening(false);
    setDurationMillis(sessionRef.current.startedAt ? Math.max(0, Date.now() - sessionRef.current.startedAt) : 0);
    if (!wasManualStop && sessionRef.current.heardSpeech) {
      setNaturalCompletionToken((current) => current + 1);
    }
    resolvePendingStop();
  });

  const startListening = useCallback(async () => {
    if (!enabled) {
      throw new Error('Live speech recognition is disabled.');
    }
    syncAvailability();
    if (!ExpoSpeechRecognitionModule.isRecognitionAvailable()) {
      throw new Error('Live speech recognition is unavailable on this device.');
    }
    const permission = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
    if (!permission.granted) {
      throw new Error('Live speech recognition permission was denied.');
    }

    const nextSessionId = sessionRef.current.sessionId + 1;
    manualStopRef.current = false;
    resetSessionState(nextSessionId);
    const speechContext = Array.from(new Set([
      ...buildSpeechRecognitionContext(wakePhrase),
      ...contextualStrings.map((value) => String(value || '').trim()).filter(Boolean),
    ]));

    ExpoSpeechRecognitionModule.start({
      lang: language === 'en' ? 'en-US' : language,
      interimResults: true,
      continuous: false,
      addsPunctuation: true,
      contextualStrings: speechContext.length ? speechContext : undefined,
      recordingOptions: ExpoSpeechRecognitionModule.supportsRecording()
        ? { persist: true }
        : undefined,
      androidIntentOptions: {
        EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS: 700,
        EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS: 1100,
        EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS: 400,
      },
    });
  }, [contextualStrings, enabled, language, resetSessionState, syncAvailability, wakePhrase]);

  const stopListening = useCallback(async () => {
    if (!sessionRef.current.sessionId) {
      return buildSnapshot(sessionRef.current);
    }
    if (!listening) {
      return buildSnapshot(sessionRef.current);
    }
    manualStopRef.current = true;
    return new Promise<RecognitionSnapshot>((resolve) => {
      const timeout = setTimeout(() => {
        resolvePendingStop();
      }, 2500);
      pendingStopRef.current = { resolve, timeout };
      ExpoSpeechRecognitionModule.stop();
    });
  }, [listening, resolvePendingStop]);

  const abortListening = useCallback(async () => {
    if (!sessionRef.current.sessionId || !listening) {
      return;
    }
    manualStopRef.current = true;
    ExpoSpeechRecognitionModule.abort();
  }, [listening]);

  return {
    available,
    supportsRecording,
    listening,
    durationMillis,
    transcript,
    interimTranscript,
    finalTranscript,
    audioUri,
    error,
    naturalCompletionToken,
    startListening,
    stopListening,
    abortListening,
    resetTranscript: () => resetSessionState(sessionRef.current.sessionId),
    currentSnapshot: () => buildSnapshot(sessionRef.current),
  };
}
