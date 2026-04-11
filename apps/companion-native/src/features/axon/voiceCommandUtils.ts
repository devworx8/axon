const WAKE_LEAD_IN_WORDS = new Set(['hey', 'hi', 'hello', 'ok', 'okay', 'yo']);
const COMMAND_LEAD_IN_WORDS = new Set(['please']);
const WAKE_TOKEN_ALIASES: Record<string, string[]> = {
  axon: ['accent'],
};

function tokenizeSpeech(value: string): string[] {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function stripLeadingTokens(tokens: string[], removable: Set<string>): string[] {
  const next = [...tokens];
  while (next.length && removable.has(next[0])) {
    next.shift();
  }
  return next;
}

function tokenMatchesWakePhrase(expected: string, actual: string): boolean {
  if (expected === actual) {
    return true;
  }
  const aliases = WAKE_TOKEN_ALIASES[expected] || [];
  return aliases.includes(actual);
}

export function buildSpeechRecognitionContext(wakePhrase: string): string[] {
  const phrase = String(wakePhrase || 'Axon').trim() || 'Axon';
  const phrases = new Set([
    phrase,
    `${phrase} what needs attention`,
    `${phrase} inspect the active workspace`,
  ]);
  if (tokenizeSpeech(phrase).join(' ') === 'axon') {
    phrases.add('Axon');
    phrases.add('Axon Online');
  }
  return Array.from(phrases);
}

export function canonicalizeWakePhraseTranscript(transcript: string, wakePhrase: string): string {
  const raw = String(transcript || '').trim();
  const phrase = String(wakePhrase || 'Axon').trim() || 'Axon';
  const wakeTokens = tokenizeSpeech(phrase);
  if (!raw || wakeTokens.length !== 1) {
    return raw;
  }

  const aliases = WAKE_TOKEN_ALIASES[wakeTokens[0]] || [];
  if (!aliases.length) {
    return raw;
  }

  const escapedLeadIns = Array.from(WAKE_LEAD_IN_WORDS)
    .map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  const escapedAliases = aliases
    .map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  const prefixPattern = new RegExp(
    `^((?:${escapedLeadIns})\\s+)?(?:${escapedAliases})(?=$|[^a-z0-9])`,
    'i',
  );

  if (!prefixPattern.test(raw)) {
    return raw;
  }
  return raw.replace(prefixPattern, (_, leadIn = '') => `${leadIn}${phrase}`);
}

export function detectWakePhrase(transcript: string, wakePhrase: string): { matched: boolean; command: string } {
  const wakeTokens = tokenizeSpeech(wakePhrase || 'Axon');
  const spokenTokens = stripLeadingTokens(tokenizeSpeech(transcript), WAKE_LEAD_IN_WORDS);
  if (!wakeTokens.length || spokenTokens.length < wakeTokens.length) {
    return { matched: false, command: '' };
  }

  const matchesWakePhrase = wakeTokens.every((token, index) => tokenMatchesWakePhrase(token, spokenTokens[index]));
  if (!matchesWakePhrase) {
    return { matched: false, command: '' };
  }

  const commandTokens = stripLeadingTokens(
    spokenTokens.slice(wakeTokens.length),
    COMMAND_LEAD_IN_WORDS,
  );
  return { matched: true, command: commandTokens.join(' ') };
}

export function isNoSpeechTranscriptError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || '');
  return /could not detect speech/i.test(message);
}
