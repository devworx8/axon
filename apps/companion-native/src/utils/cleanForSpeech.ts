/**
 * Axon — Clean text for TTS speech.
 * Strips markdown formatting, normalizes paths, removes artifacts.
 * Mirror of axon_api/services/tts_sanitizer.py for client-side use.
 */

const SPOKEN_CODE_LABELS: Record<string, string> = {
  bash: 'shell',
  js: 'JavaScript',
  jsx: 'JSX',
  py: 'Python',
  sh: 'shell',
  ts: 'TypeScript',
  tsx: 'TSX',
  zsh: 'shell',
};

const SPOKEN_COMMANDS = /\b(?:git|npm|npx|pnpm|yarn|node|python|python3|pip|pip3|bash|zsh|curl|gh|vercel)\b/gi;
const UPPER_SNAKE_TOKEN = /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/g;
const DOTTED_FILE_TOKEN = /\b([A-Za-z0-9_-]+)\.(py|js|ts|tsx|jsx|json|md|css|html|sh|yaml|yml|env)\b/g;
const DOTTED_IDENTIFIER_TOKEN = /\b([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\b/g;
const FILE_LABELS: Record<string, string> = {
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

function spokenCodeLabel(label: string): string {
  const normalized = String(label || '').trim().toLowerCase();
  return SPOKEN_CODE_LABELS[normalized] || normalized;
}

function humanizeUpperSnakeCase(value: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function humanizeFileToken(stem: string, ext: string): string {
  return `${String(stem || '').replace(/[_-]+/g, ' ').trim()} ${FILE_LABELS[String(ext || '').toLowerCase()] || ext}`;
}

function humanizeCodeSnippet(text: string): string {
  let t = String(text || '').replace(/\r/g, '\n').trim();
  if (!t) return '';
  t = t.replace(SPOKEN_COMMANDS, (match) => match.toLowerCase());
  t = t.replace(UPPER_SNAKE_TOKEN, (match) => humanizeUpperSnakeCase(match));
  t = t.replace(DOTTED_FILE_TOKEN, (_match, stem: string, ext: string) => humanizeFileToken(stem, ext));
  t = t.replace(DOTTED_IDENTIFIER_TOKEN, (_match, left: string, right: string) => `${left} dot ${right}`);
  t = t.replace(/(^|\s)--([a-z0-9][a-z0-9-]*)/gi, (_match, prefix: string, flag: string) => `${prefix}${flag} flag`);
  t = t.replace(/(^|\s)-([a-z])\b/gi, (_match, prefix: string, flag: string) => `${prefix}${flag.toLowerCase()} flag`);
  t = t.replace(/!==/g, ' is not exactly equal to ');
  t = t.replace(/===/g, ' is exactly equal to ');
  t = t.replace(/!=/g, ' is not equal to ');
  t = t.replace(/==/g, ' is equal to ');
  t = t.replace(/=>/g, ' returns ');
  t = t.replace(/\+\+/g, ' increment ');
  t = t.replace(/--/g, ' decrement ');
  t = t.replace(/<=/g, ' is less than or equal to ');
  t = t.replace(/>=/g, ' is greater than or equal to ');
  t = t.replace(/[{}[\]();,]/g, ' ');
  t = t.replace(/\//g, ' slash ');
  t = t.replace(/=/g, ' equals ');
  t = t.replace(/:/g, ' ');
  t = t.replace(/\n+/g, '. ');
  return t.replace(/\s+/g, ' ').trim();
}

function replaceFencedCode(_match: string, language: string, code: string): string {
  const spoken = humanizeCodeSnippet(code);
  if (!spoken) return ' ';
  const label = spokenCodeLabel(language);
  return label ? ` In ${label}, ${spoken}. ` : ` ${spoken}. `;
}

function replaceInlineCode(_match: string, code: string): string {
  const spoken = humanizeCodeSnippet(code);
  return spoken ? ` ${spoken} ` : ' ';
}

export function cleanForSpeech(text: string): string {
  if (!text) return '';
  let t = String(text);

  // Fenced and inline code → plain spoken phrasing
  t = t.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, replaceFencedCode);
  t = t.replace(/`([^`]+)`/g, replaceInlineCode);
  // Images → alt text
  t = t.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1');
  // Links → label only
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  // HTML tags
  t = t.replace(/<[^>]+>/g, '');
  // Headings
  t = t.replace(/^#{1,6}\s+/gm, '');
  // Bold / italic / strikethrough
  t = t.replace(/\*\*([^*]+)\*\*/g, '$1');
  t = t.replace(/__([^_]+)__/g, '$1');
  t = t.replace(/\*([^*]+)\*/g, '$1');
  t = t.replace(/_([^_]+)_/g, '$1');
  t = t.replace(/~~([^~]+)~~/g, '$1');
  // Lists
  t = t.replace(/^[-*+]\s+/gm, '');
  t = t.replace(/^\d+\.\s+/gm, '');
  // Blockquotes
  t = t.replace(/^>\s*/gm, '');
  // Horizontal rules
  t = t.replace(/^---+$/gm, '');
  // Table artifacts
  t = t.replace(/^[-|: ]+$/gm, '');
  t = t.replace(/[|]/g, ' ');
  // Backslash escapes
  t = t.replace(/\\([^\\])/g, '$1');
  // File paths → spoken form: /home/edp/Downloads → "home, edp, Downloads"
  t = t.replace(
    /(?<!\w)([/~](?:[a-zA-Z0-9._-]+\/)+[a-zA-Z0-9._-]+)/g,
    (_match, path: string) => {
      const parts = path.replace(/^~/, 'home').split('/').filter(Boolean);
      return parts.length > 1 ? parts.join(', ') : path;
    },
  );
  t = t.replace(SPOKEN_COMMANDS, (match) => match.toLowerCase());
  t = t.replace(UPPER_SNAKE_TOKEN, (match) => humanizeUpperSnakeCase(match));
  t = t.replace(DOTTED_FILE_TOKEN, (_match, stem: string, ext: string) => humanizeFileToken(stem, ext));
  t = t.replace(DOTTED_IDENTIFIER_TOKEN, (_match, left: string, right: string) => `${left} dot ${right}`);
  t = t.replace(/(^|\s)--([a-z0-9][a-z0-9-]*)/gi, (_match, prefix: string, flag: string) => `${prefix}${flag} flag`);
  t = t.replace(/(^|\s)-([a-z])\b/gi, (_match, prefix: string, flag: string) => `${prefix}${flag.toLowerCase()} flag`);
  // Collapse whitespace
  t = t.replace(/\n{3,}/g, '\n\n');
  t = t.replace(/[ \t]+\n/g, '\n');
  t = t.replace(/\n[ \t]+/g, '\n');
  t = t.replace(/[ \t]{2,}/g, ' ');
  return t.trim();
}
