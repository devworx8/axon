import { useCallback, useEffect, useRef, useState } from 'react';
import * as Speech from 'expo-speech';

export function useSpeechReply(enabled: boolean) {
  const [speaking, setSpeaking] = useState(false);
  const lastAutoSpoken = useRef('');

  const stop = useCallback(() => {
    Speech.stop();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text: string) => {
    const message = String(text || '').trim();
    if (!message) return;
    Speech.stop();
    setSpeaking(true);
    Speech.speak(message, {
      rate: 0.98,
      pitch: 1.0,
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
