import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import * as Speech from 'expo-speech';

import { speakAxonReply } from '@/api/axon';
import { pickBestVoice, VOICE_RATE, VOICE_PITCH } from '@/utils/pickVoice';
import { cleanForSpeech } from '@/utils/cleanForSpeech';
import type { AxonVoiceProvider, CompanionConfig } from '@/types/companion';

type AxonSpeechSettings = {
  axonVoiceProvider: AxonVoiceProvider | string;
  axonVoiceIdentity: string;
};

function fallbackLocale(voiceIdentity: string) {
  const voice = String(voiceIdentity || '').trim();
  if (voice.startsWith('af-ZA')) return 'af-ZA';
  if (voice.startsWith('en-GB')) return 'en-GB';
  if (voice.startsWith('en-US')) return 'en-US';
  return 'en-ZA';
}

export function useAxonSpeech(
  enabled: boolean,
  config: CompanionConfig,
  settings: AxonSpeechSettings,
) {
  const player = useAudioPlayer();
  const status = useAudioPlayerStatus(player);
  const lastAutoSpoken = useRef('');
  const [fallbackSpeaking, setFallbackSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState<string>(String(settings.axonVoiceProvider || 'cloud'));
  const speaking = Boolean(status.playing || fallbackSpeaking);
  const voiceIdRef = useRef<string | undefined>(undefined);

  /* Resolve shared voice once (same prefs as desktop) */
  useEffect(() => {
    pickBestVoice().then(id => { voiceIdRef.current = id; });
  }, []);

  const stop = useCallback(() => {
    Speech.stop();
    setFallbackSpeaking(false);
    try {
      player.pause();
    } catch {}
    player.seekTo(0).catch(() => undefined);
  }, [player]);

  const speakFallback = useCallback((text: string) => {
    const message = cleanForSpeech(text);
    if (!message) return;
    Speech.stop();
    setFallbackSpeaking(true);
    setProvider('device');
    Speech.speak(message, {
      rate: VOICE_RATE,
      pitch: VOICE_PITCH,
      ...(voiceIdRef.current ? { voice: voiceIdRef.current } : { language: fallbackLocale(settings.axonVoiceIdentity) }),
      onDone: () => { setFallbackSpeaking(false); },
      onStopped: () => { setFallbackSpeaking(false); },
      onError: () => { setFallbackSpeaking(false); },
    });
  }, [settings.axonVoiceIdentity]);

  const speak = useCallback(async (text: string) => {
    const message = cleanForSpeech(text);
    if (!enabled || !message) return;
    setError(null);
    stop();
    try {
      const reply = await speakAxonReply(
        {
          text: message,
          preferred_provider: settings.axonVoiceProvider,
          voice_identity: settings.axonVoiceIdentity,
        },
        config,
      );
      const mediaType = String(reply.media_type || 'audio/mpeg').trim() || 'audio/mpeg';
      const source = `data:${mediaType};base64,${reply.audio_base64}`;
      player.replace(source);
      player.play();
      setProvider(String(reply.provider || settings.axonVoiceProvider || 'cloud'));
    } catch (nextError) {
      const messageText = nextError instanceof Error ? nextError.message : 'Axon speech failed';
      setError(messageText);
      speakFallback(message);
    }
  }, [config, enabled, player, settings.axonVoiceIdentity, settings.axonVoiceProvider, speakFallback, stop]);

  const autoSpeak = useCallback((text: string) => {
    const message = String(text || '').trim();
    if (!enabled || !message || message === lastAutoSpoken.current) {
      return;
    }
    lastAutoSpoken.current = message;
    speak(message).catch(() => undefined);
  }, [enabled, speak]);

  useEffect(() => {
    if (!enabled) {
      stop();
    }
  }, [enabled, stop]);

  return useMemo(() => ({
    speaking,
    provider,
    error,
    speak,
    stop,
    autoSpeak,
  }), [error, provider, speak, speaking, stop, autoSpeak]);
}
