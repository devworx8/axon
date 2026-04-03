/* ══════════════════════════════════════════════════════════════
   Axon — Chat Follow-Up Suggestions
   ══════════════════════════════════════════════════════════════ */

function axonNormalizeFollowUpSuggestion(text) {
  const raw = String(text || '')
    .replace(/^[-*]\s+/, '')
    .replace(/^["'`“”]+|["'`“”]+$/g, '');
  const normalized = raw.replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  const continueLike = normalized.replace(/[.!?]+$/, '');
  if (/^(?:→\s*)?continue$/i.test(continueLike) || /^(?:please\s+)?continue$/i.test(continueLike)) {
    return '→ Continue';
  }
  return normalized;
}

function axonIsFollowUpPromptCandidate(text) {
  const value = axonNormalizeFollowUpSuggestion(text);
  if (!value) return false;
  if (value === '→ Continue') return true;
  if (value.length > 64) return false;
  if (/\n|https?:\/\//i.test(value)) return false;
  if (/^[`*_#]+$/.test(value)) return false;
  const words = value.split(/\s+/).filter(Boolean);
  return words.length > 0 && words.length <= 8;
}

function axonCollectFollowUpMatches(response, pattern) {
  const matches = [];
  const text = String(response || '');
  let match = null;
  while ((match = pattern.exec(text)) !== null) {
    const candidate = axonNormalizeFollowUpSuggestion(match[1]);
    if (axonIsFollowUpPromptCandidate(candidate)) {
      matches.push(candidate);
    }
  }
  return matches;
}

function axonExtractExplicitFollowUpPrompts(response) {
  const patterns = [
    /(?:reply|respond|say|type)\s+(?:with\s+)?`([^`\n]{1,80})`/gi,
    /(?:reply|respond|say|type)\s+(?:with\s+)?["“]([^"\n”]{1,80})["”]/gi,
    /(?:reply|respond|say|type)\s+(?:with\s+)?'([^'\n]{1,80})'/gi,
    /(?:reply|respond|say|type)\s+with\s+([a-z0-9][a-z0-9 /:_-]{1,60}?)(?=(?:\s+(?:and|then|so|if)\b)|[.!?,;:]|$)/gi,
    /(?:reply|respond|say|type)\s+(?!with\b)([a-z0-9][a-z0-9 /:_-]{1,60}?)(?=(?:\s+(?:and|then|so|if)\b)|[.!?,;:]|$)/gi,
  ];
  return patterns.flatMap((pattern) => axonCollectFollowUpMatches(response, pattern));
}

function axonDeduplicateFollowUpSuggestions(suggestions) {
  const deduped = [];
  const seen = new Set();
  for (const suggestion of suggestions || []) {
    const normalized = axonNormalizeFollowUpSuggestion(suggestion);
    if (!axonIsFollowUpPromptCandidate(normalized)) continue;
    const key = normalized.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(normalized);
  }
  return deduped;
}

function axonResponseRequestsContinuation(response) {
  const lines = String(response || '')
    .split(/\n+/)
    .map((line) => axonNormalizeFollowUpSuggestion(line))
    .filter(Boolean);
  return lines.some((line) => line === '→ Continue');
}

function axonBuildFollowUpSuggestions(response, userMessage) {
  const suggestions = axonExtractExplicitFollowUpPrompts(response);
  const lower = String(response || '').toLowerCase();

  if (axonResponseRequestsContinuation(response)) {
    suggestions.push('→ Continue');
  }
  if (/\b(created|saved|added)\b.{0,30}\b(mission|task)/i.test(response)) {
    suggestions.push('Show my active missions');
  }
  if (/\b(created|saved|added)\b.{0,30}\b(playbook|prompt)/i.test(response)) {
    suggestions.push('Open playbooks');
  }
  if (/```[\s\S]{20,}```/.test(response)) {
    suggestions.push('Explain this code');
    suggestions.push('Optimize this code');
  }
  if (/\b(plan|roadmap|strategy|steps?)\b/i.test(response) && suggestions.length < 3) {
    suggestions.push('Turn this into missions');
  }
  if (/\b(error|bug|issue|fix)\b/i.test(lower) && suggestions.length < 3) {
    suggestions.push('How do I debug this?');
  }
  if (/\b(api|endpoint|route)\b/i.test(lower) && suggestions.length < 3) {
    suggestions.push('Show example request');
  }

  const deduped = axonDeduplicateFollowUpSuggestions(suggestions);
  if (deduped.length === 0) {
    deduped.push('Tell me more', 'What should I do next?');
  } else if (deduped.length === 1) {
    deduped.push('What should I do next?');
  }
  return deduped.slice(0, 3);
}

function axonApplyFollowUpSuggestions(response, userMessage) {
  this.followUpSuggestions = axonBuildFollowUpSuggestions(response, userMessage);
}

function axonUseFollowUpSuggestion(text) {
  this.followUpSuggestions = [];
  const suggestion = axonNormalizeFollowUpSuggestion(text);
  const message = suggestion === '→ Continue' ? 'please continue' : String(text || '').trim();
  this.chatInput = message;
  this.$nextTick(() => this.sendChat());
}
