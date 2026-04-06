/**
 * Axon — Clean text for TTS speech.
 * Strips markdown formatting, normalizes paths, removes artifacts.
 * Mirror of axon_api/services/tts_sanitizer.py for client-side use.
 */

export function cleanForSpeech(text: string): string {
  if (!text) return '';
  let t = String(text);

  // Fenced code blocks → remove entirely
  t = t.replace(/```[^\n`]*\n?[\s\S]*?```/g, ' ');
  // Inline code → just the content
  t = t.replace(/`([^`]+)`/g, '$1');
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
  // Collapse whitespace
  t = t.replace(/\n{3,}/g, '\n\n');
  t = t.replace(/[ \t]+\n/g, '\n');
  t = t.replace(/\n[ \t]+/g, '\n');
  t = t.replace(/[ \t]{2,}/g, ' ');
  return t.trim();
}
