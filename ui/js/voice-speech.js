/* ══════════════════════════════════════════════════════════════
   Axon — Voice Speech Helpers
   ══════════════════════════════════════════════════════════════ */

const AXON_VOICE_CODE_TOKEN_REPLACEMENTS = [
  [/!==/g, ' not equal equal '],
  [/===/g, ' equal equal equal '],
  [/=>/g, ' arrow '],
  [/\+\+/g, ' plus plus '],
  [/--/g, ' minus minus '],
  [/&&/g, ' and '],
  [/\|\|/g, ' or '],
  [/!=/g, ' not equal '],
  [/==/g, ' equal equal '],
  [/<=/g, ' less than or equal to '],
  [/>=/g, ' greater than or equal to '],
  [/\{/g, ' open brace '],
  [/\}/g, ' close brace '],
  [/\[/g, ' open bracket '],
  [/\]/g, ' close bracket '],
  [/\(/g, ' open parenthesis '],
  [/\)/g, ' close parenthesis '],
  [/;/g, ' semicolon '],
  [/:/g, ' colon '],
  [/,/g, ' comma '],
  [/\./g, ' dot '],
  [/=/g, ' equals '],
  [/\+/g, ' plus '],
  [/-/g, ' minus '],
  [/\*/g, ' star '],
  [/\//g, ' slash '],
];

function voiceCodeLabel(label = '') {
  return String(label || '')
    .replace(/[^a-z0-9#+.-]+/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeVoiceCode(code = '') {
  let value = String(code || '').replace(/\r/g, '\n').trim();
  if (!value) return '';
  value = value.replace(/\t/g, ' tab ');
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
  const intro = label ? `${label} code block.` : 'Code block.';
  if (!spokenCode) return ` ${intro} `;
  return ` ${intro} ${spokenCode}. End code block. `;
}

function replaceVoiceInlineCode(_match, code = '') {
  const spokenCode = normalizeVoiceCode(code);
  if (!spokenCode) return ' ';
  return ` inline code ${spokenCode} `;
}

function cleanVoiceSpeechText(text) {
  return String(text || '')
    .replace(/```([^\n`]*)\n?([\s\S]*?)```/g, replaceVoiceCodeBlock)
    .replace(/`([^`]+)`/g, replaceVoiceInlineCode)
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
  splitText: splitVoiceSpeechText,
};
