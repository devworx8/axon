import { useCallback, useEffect, useRef, useState } from 'react';
import * as Speech from 'expo-speech';
import { pickBestVoice, VOICE_RATE, VOICE_PITCH } from '@/utils/pickVoice';
import { cleanForSpeech } from '@/utils/cleanForSpeech';

export function useSpeechReply(enabled: boolean) {
  const [speaking, setSpeaking] = useState(false);
  const lastAutoSpoken = useRef('');
  const voiceId = useRef<string | undefined>(undefined);

  /* Resolve voice once (same prefs as desktop _pickBestBrowserVoice) */
  useEffect(() => {
    pickBestVoice().then(id => { voiceId.current = id; });
  }, []);

  const stop = useCallback(() => {
    Speech.stop();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text: string) => {
    const message = cleanForSpeech(text);
    if (!message) return;
    Speech.stop();
    setSpeaking(true);
    Speech.speak(message, {
      rate: VOICE_RATE,
      pitch: VOICE_PITCH,
      ...(voiceId.current ? { voice: voiceId.current } : { language: 'en-GB' }),
      onDone: () => setSpeaking(false),
      onStopped: () => setSpeaking(false),
      onError: () => setSpeaking(false),
    });
  }, []);

  const autoSpeak = useCallback((text: string) => {
    const message = String(text || '').trim();
    if (!enabled || !message || message === lastAutoSpoken.current) {
      return;
    }
    lastAutoSpoken.current = message;
    speak(message);
  }, [enabled, speak]);

  useEffect(() => {
    if (!enabled) {
      stop();
    }
  }, [enabled, stop]);

  return { speaking, speak, stop, autoSpeak };
}
