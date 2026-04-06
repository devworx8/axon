const WAKE_LEAD_IN_WORDS = new Set(['hey', 'hi', 'hello', 'ok', 'okay', 'yo']);
const COMMAND_LEAD_IN_WORDS = new Set(['please']);

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

export function detectWakePhrase(transcript: string, wakePhrase: string): { matched: boolean; command: string } {
  const wakeTokens = tokenizeSpeech(wakePhrase || 'Axon');
  const spokenTokens = stripLeadingTokens(tokenizeSpeech(transcript), WAKE_LEAD_IN_WORDS);
  if (!wakeTokens.length || spokenTokens.length < wakeTokens.length) {
    return { matched: false, command: '' };
  }

  const matchesWakePhrase = wakeTokens.every((token, index) => spokenTokens[index] === token);
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
