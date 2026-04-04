import { useCallback } from 'react';
import { useAudioPlayer } from 'expo-audio';

const AXON_BOOT_SOUND = require('../../assets/axon-online.wav');

export function useAxonBootSound(enabled: boolean) {
  const player = useAudioPlayer(AXON_BOOT_SOUND);

  const play = useCallback(async () => {
    if (!enabled) {
      return false;
    }
    try {
      await player.seekTo(0);
      player.play();
      return true;
    } catch {
      return false;
    }
  }, [enabled, player]);

  return { play };
}
