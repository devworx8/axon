/* ══════════════════════════════════════════════════════════════
   Axon — Voice Speech Helpers
   ══════════════════════════════════════════════════════════════ */

const AXON_VOICE_CODE_LABELS = {
  bash: 'shell',
  js: 'JavaScript',
  jsx: 'JSX',
  py: 'Python',
  sh: 'shell',
  ts: 'TypeScript',
  tsx: 'TSX',
  zsh: 'shell',
};

const AXON_VOICE_CODE_TOKEN_REPLACEMENTS = [
  [/!==/g, ' is not exactly equal to '],
  [/===/g, ' is exactly equal to '],
  [/!=/g, ' is not equal to '],
  [/==/g, ' is equal to '],
  [/=>/g, ' returns '],
  [/\+\+/g, ' increment '],
  [/--/g, ' decrement '],
  [/&&/g, ' and '],
  [/\|\|/g, ' or '],
  [/<=/g, ' is less than or equal to '],
  [/>=/g, ' is greater than or equal to '],
  [/[{}[\]();,]/g, ' '],
  [/\//g, ' slash '],
  [/=/g, ' equals '],
  [/:/g, ' '],
];

const AXON_VOICE_COMMAND_RE = /\b(?:git|npm|npx|pnpm|yarn|node|python|python3|pip|pip3|bash|zsh|curl|gh|vercel)\b/gi;
const AXON_VOICE_ENV_VAR_RE = /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/g;
const AXON_VOICE_DOTTED_FILE_RE = /\b([A-Za-z0-9_-]+)\.(py|js|ts|tsx|jsx|json|md|css|html|sh|yaml|yml|env)\b/g;
const AXON_VOICE_DOTTED_IDENTIFIER_RE = /\b([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\b/g;
const AXON_VOICE_PERMISSION_ENABLE_RE = /\b(?:enable|turn on|activate|grant|enter|switch to|use)\b/i;
const AXON_VOICE_PERMISSION_DISABLE_RE = /\b(?:disable|turn off|deactivate|exit|leave|switch off|switch back)\b/i;
const AXON_VOICE_PERMISSION_TOGGLE_RE = /\b(?:toggle|flip)\b/i;
const AXON_VOICE_FILE_LABELS = {
  py: 'Python file',
  js: 'JavaScript file',
  ts: 'TypeScript file',
  tsx: 'TSX file',
  jsx: 'JSX file',
  json: 'JSON file',
  md: 'Markdown file',
  css: 'CSS file',
  html: 'HTML file',
  sh: 'shell script',
  yaml: 'YAML file',
  yml: 'YAML file',
  env: 'env file',
};
const AXON_WAKE_LEAD_IN_WORDS = ['hey', 'hi', 'hello', 'ok', 'okay', 'yo', 'please', 'listen'];
const AXON_WAKE_TOKEN_ALIASES = {
  axon: ['accent'],
};

function escapeVoiceSpeechRegex(value = '') {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function tokenizeWakePhrase(value = '') {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function canonicalizeWakePhraseTranscript(transcript = '', wakePhrase = 'Axon') {
  const raw = String(transcript || '').trim();
  const phrase = String(wakePhrase || 'Axon').trim() || 'Axon';
  const wakeTokens = tokenizeWakePhrase(phrase);
  if (!raw || wakeTokens.length !== 1) return raw;

  const aliases = AXON_WAKE_TOKEN_ALIASES[wakeTokens[0]] || [];
  if (!aliases.length) return raw;

  const escapedLeadIns = AXON_WAKE_LEAD_IN_WORDS.map(escapeVoiceSpeechRegex).join('|');
  const escapedAliases = aliases.map(escapeVoiceSpeechRegex).join('|');
  const prefixPattern = new RegExp(
    `^((?:${escapedLeadIns})\\s+)?(?:${escapedAliases})(?=$|[^a-z0-9])`,
    'i',
  );
  if (!prefixPattern.test(raw)) return raw;
  return raw.replace(prefixPattern, (_match, leadIn = '') => `${leadIn}${phrase}`);
}

function voiceCodeLabel(label = '') {
  const normalized = String(label || '')
    .replace(/[^a-z0-9#+.-]+/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return AXON_VOICE_CODE_LABELS[normalized.toLowerCase()] || normalized;
}

function humanizeUpperSnakeToken(value = '') {
  return String(value || '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function humanizeFileToken(stem = '', ext = '') {
  return `${String(stem || '').replace(/[_-]+/g, ' ').trim()} ${AXON_VOICE_FILE_LABELS[String(ext || '').toLowerCase()] || ext}`.trim();
}

function normalizeVoiceCode(code = '') {
  let value = String(code || '').replace(/\r/g, '\n').trim();
  if (!value) return '';
  value = value.replace(/\t/g, ' tab ');
  value = value.replace(AXON_VOICE_COMMAND_RE, (match) => match.toLowerCase());
  value = value.replace(AXON_VOICE_ENV_VAR_RE, (match) => humanizeUpperSnakeToken(match));
  value = value.replace(AXON_VOICE_DOTTED_FILE_RE, (_match, stem, ext) => humanizeFileToken(stem, ext));
  value = value.replace(AXON_VOICE_DOTTED_IDENTIFIER_RE, (_match, left, right) => `${left} dot ${right}`);
  value = value.replace(/(^|\s)--([a-z0-9][a-z0-9-]*)/gi, (_match, prefix, flag) => `${prefix}${flag} flag`);
  value = value.replace(/(^|\s)-([a-z])\b/gi, (_match, prefix, flag) => `${prefix}${flag.toLowerCase()} flag`);
  AXON_VOICE_CODE_TOKEN_REPLACEMENTS.forEach(([pattern, replacement]) => {
    value = value.replace(pattern, replacement);
  });
  value = value
    .replace(/\n{2,}/g, '\n')
    .split('\n')
    .map(line => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('. ');
  return value.replace(/\s+/g, ' ').trim();
}

function replaceVoiceCodeBlock(_match, language = '', code = '') {
  const spokenCode = normalizeVoiceCode(code);
  const label = voiceCodeLabel(language);
  if (!spokenCode) return ' ';
  return label ? ` In ${label}, ${spokenCode}. ` : ` ${spokenCode}. `;
}

function replaceVoiceInlineCode(_match, code = '') {
  const spokenCode = normalizeVoiceCode(code);
  if (!spokenCode) return ' ';
  return ` ${spokenCode} `;
}

function cleanVoiceSpeechText(text) {
  return String(text || '')
    .replace(/```([^\n`]*)\n?([\s\S]*?)```/g, replaceVoiceCodeBlock)
    .replace(/`([^`]+)`/g, replaceVoiceInlineCode)
    .replace(AXON_VOICE_ENV_VAR_RE, (match) => humanizeUpperSnakeToken(match))
    .replace(AXON_VOICE_DOTTED_FILE_RE, (_match, stem, ext) => humanizeFileToken(stem, ext))
    .replace(AXON_VOICE_DOTTED_IDENTIFIER_RE, (_match, left, right) => `${left} dot ${right}`)
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/^>\s+/gm, '')
    .replace(/^---+$/gm, '')
    .replace(/[|\\]/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .trim();
}

function normalizeVoiceCommandText(text = '') {
  const raw = String(text || '').trim();
  if (!raw) return raw;
  const lower = raw.toLowerCase();
  if (!/(slash|backslash|dot|point|path|file|folder|directory|\/|\\)/.test(lower)) return raw;
  let next = raw;
  next = next.replace(/\s+(back\s*slash|backslash)\s+/gi, '\\');
  next = next.replace(/\s+slash\s+/gi, '/');
  next = next.replace(/\s+(dot|point)\s+/gi, '.');
  next = next.replace(/\s+(dash|hyphen)\s+/gi, '-');
  next = next.replace(/\s+underscore\s+/gi, '_');
  next = next.replace(/\s*\/\s*/g, '/');
  next = next.replace(/\s*\\\s*/g, '\\');
  return next.replace(/\s+/g, ' ').trim();
}

function detectVoicePermissionPreset(text = '') {
  const lower = String(text || '').trim().toLowerCase();
  if (!lower) return '';
  if (/(?:full access|full-access|fullaccess)\b/.test(lower)) return 'full_access';
  if (/(?:ask first|ask-first)\b/.test(lower)) return 'ask_first';
  if (/(?:default permissions|default mode|safe mode|normal mode|\bdefault\b)/.test(lower)) return 'default';
  return '';
}

async function voicePermissionCommand(text = '', options = {}) {
  const lower = String(text || '').trim().toLowerCase();
  if (!lower) return false;
  const setPermissionPreset = typeof options.setPermissionPreset === 'function'
    ? options.setPermissionPreset
    : null;
  if (!setPermissionPreset) return false;
  const permissionPresetKey = typeof options.permissionPresetKey === 'function'
    ? options.permissionPresetKey
    : null;
  const preset = detectVoicePermissionPreset(lower);
  if (!preset) return false;
  const action = AXON_VOICE_PERMISSION_DISABLE_RE.test(lower)
    ? 'disable'
    : AXON_VOICE_PERMISSION_ENABLE_RE.test(lower)
      ? 'enable'
      : AXON_VOICE_PERMISSION_TOGGLE_RE.test(lower)
        ? 'toggle'
        : '';

  let target = preset;
  if (action === 'toggle') {
    const current = permissionPresetKey ? String(permissionPresetKey() || '').trim().toLowerCase() : '';
    target = current === preset
      ? (preset === 'default' ? 'ask_first' : 'default')
      : preset;
  } else if (action === 'disable') {
    target = preset === 'default' ? 'ask_first' : 'default';
  } else if (action === 'enable') {
    target = preset;
  }

  await setPermissionPreset(target);
  return true;
}

function splitVoiceSpeechText(text, maxChunkLength = 420) {
  const clean = cleanVoiceSpeechText(text);
  if (!clean) return [];
  const limit = Math.max(140, Number(maxChunkLength || 0) || 420);
  const chunks = [];

  const pushChunk = (chunk) => {
    const value = String(chunk || '').replace(/\s+/g, ' ').trim();
    if (value) chunks.push(value);
  };

  const splitLongSentence = (sentence) => {
    const words = String(sentence || '').split(/\s+/).filter(Boolean);
    let current = '';
    for (const word of words) {
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > limit && current) {
        pushChunk(current);
        current = word;
      } else {
        current = candidate;
      }
    }
    pushChunk(current);
  };

  const consumeBlock = (block) => {
    const sentences = String(block || '').match(/[^.!?]+(?:[.!?]+|$)/g) || [String(block || '')];
    let current = '';
    for (const rawSentence of sentences) {
      const sentence = String(rawSentence || '').replace(/\s+/g, ' ').trim();
      if (!sentence) continue;
      const candidate = current ? `${current} ${sentence}` : sentence;
      if (candidate.length <= limit) {
        current = candidate;
        continue;
      }
      if (current) pushChunk(current);
      if (sentence.length <= limit) {
        current = sentence;
      } else {
        splitLongSentence(sentence);
        current = '';
      }
    }
    pushChunk(current);
  };

  const paragraphs = clean.split(/\n{2,}/).map(part => part.trim()).filter(Boolean);
  if (paragraphs.length) {
    paragraphs.forEach(consumeBlock);
  } else {
    consumeBlock(clean);
  }
  return chunks;
}

window.axonVoiceSpeech = {
  cleanText: cleanVoiceSpeechText,
  canonicalizeWakePhraseTranscript,
  normalizeCommandText: normalizeVoiceCommandText,
  permissionCommand: voicePermissionCommand,
  splitText: splitVoiceSpeechText,
};
