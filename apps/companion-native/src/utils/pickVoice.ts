/**
 * Shared voice selection — mirrors desktop _pickBestBrowserVoice() preferences.
 *
 * Desktop priority (voice-playback.js):
 *   1. google.*uk.*english.*female
 *   2. google.*us.*english
 *   3. microsoft.*zira
 *   4. microsoft.*david
 *   5. samantha
 *   6. karen
 *   7. daniel
 *   8. \bnatural\b, \bneural\b, \benhanced\b, \bpremium\b
 *   9. any en voice (remote first)
 *
 * expo-speech voices have platform-specific names (e.g.
 * "com.apple.ttsbundle.Daniel-compact" on iOS,
 * "en-gb-x-rjs#male_1-local" on Android).  We test the same
 * patterns against both `name` and `identifier`.
 */
import * as Speech from 'expo-speech';

let _cached: Speech.Voice | null = null;

const PREFS: RegExp[] = [
  /microsoft.*david/i,
  /\bdaniel\b/i,
  /google.*uk.*english.*male/i,
  /google.*us.*english/i,
  /\bnatural\b/i,
  /\bneural\b/i,
  /\benhanced\b/i,
  /\bpremium\b/i,
];

function matchVoice(v: Speech.Voice, pref: RegExp): boolean {
  return pref.test(v.name ?? '') || pref.test(v.identifier ?? '');
}

/**
 * Returns the identifier of the best available voice,
 * using the same preference list as the desktop Axon voice.
 * Caches the result after the first successful lookup.
 */
export async function pickBestVoice(): Promise<string | undefined> {
  if (_cached) return _cached.identifier;
  try {
    const voices = await Speech.getAvailableVoicesAsync();
    if (!voices?.length) return undefined;

    /* Walk through desktop-equivalent preference list */
    for (const pref of PREFS) {
      const match = voices.find(v => matchVoice(v, pref));
      if (match) { _cached = match; return match.identifier; }
    }

    /* Fallback: any English voice (prefer en-GB for JARVIS feel) */
    const enGb = voices.find(v =>
      v.language?.startsWith('en-GB') || v.language?.startsWith('en_GB'),
    );
    if (enGb) { _cached = enGb; return enGb.identifier; }

    const enAny = voices.find(v =>
      v.language?.startsWith('en'),
    );
    if (enAny) { _cached = enAny; return enAny.identifier; }
  } catch { /* ignore — platform may not support voice listing */ }
  return undefined;
}

/** Clear cached voice (e.g. after language change) */
export function clearVoiceCache() {
  _cached = null;
}

/**
 * Shared speech rate and pitch values.
 * These match Axon's runtime defaults when no explicit voice settings are stored:
 *   voiceSpeechRate()  → 0.85
 *   voiceSpeechPitch() → 1.04
 * Greeting overrides:
 *   _greetingRateOverride → 0.15
 */
export const VOICE_RATE = 0.85;
export const VOICE_PITCH = 1.04;
export const GREETING_RATE = 0.15;
export const GREETING_PITCH = 1.04;
