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

function axonOperationalFallbackSuggestions(response) {
  const lower = String(response || '').toLowerCase();
  if (/```[\s\S]{20,}```/.test(response)) {
    return ['Inspect related files', 'Generate patch plan', 'Check blockers'];
  }
  if (/\b(api|endpoint|route|handler)\b/i.test(lower)) {
    return ['Inspect the route handler', 'Show example request', 'Check blockers'];
  }
  if (/\b(error|bug|issue|fix|failed|failure|crash)\b/i.test(lower)) {
    return ['Inspect failing path', 'Check blockers', 'Show active runs'];
  }
  if (/\b(plan|roadmap|strategy|steps?)\b/i.test(lower)) {
    return ['Turn this into missions', 'Inspect related files', 'Check blockers'];
  }
  if (/\b(branch|repo|repository|git|commit)\b/i.test(lower)) {
    return ['Show git status', 'Inspect related files', 'Check blockers'];
  }
  return ['Inspect related files', 'Check blockers', 'Show active runs'];
}

function axonBuildFollowUpSuggestions(response, userMessage) {
  const suggestions = axonExtractExplicitFollowUpPrompts(response);

  if (axonResponseRequestsContinuation(response)) {
    suggestions.push('→ Continue');
  }
  if (/\b(created|saved|added)\b.{0,30}\b(mission|task)/i.test(response)) {
    suggestions.push('Show my active missions');
  }
  if (/\b(created|saved|added)\b.{0,30}\b(playbook|prompt)/i.test(response)) {
    suggestions.push('Open playbooks');
  }

  const deduped = axonDeduplicateFollowUpSuggestions(suggestions);
  const fallbacks = axonOperationalFallbackSuggestions(response);
  for (const suggestion of fallbacks) {
    if (deduped.length >= 3) break;
    if (!deduped.some((item) => item.toLowerCase() === suggestion.toLowerCase())) {
      deduped.push(suggestion);
    }
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

function axonChatFollowUpsMixin() {
  return {
    followUpSuggestions: [],
    _followUpSourceMessageId: null,

    clearFollowUpSuggestions() {
      this.followUpSuggestions = [];
      this._followUpSourceMessageId = null;
    },

    applyFollowUpSuggestions(response, userMessage, messageId = null) {
      axonApplyFollowUpSuggestions.call(this, response, userMessage);
      this._followUpSourceMessageId = messageId;
    },

    syncFollowUpSuggestions() {
      if (this.chatLoading) {
        this.clearFollowUpSuggestions();
        return;
      }

      const messages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
      const assistantIndex = [...messages]
        .map((message, index) => ({ message, index }))
        .reverse()
        .find(({ message }) => message?.role === 'assistant' && !message.streaming && !message.error)?.index;

      if (typeof assistantIndex !== 'number') {
        this.clearFollowUpSuggestions();
        return;
      }

      const assistantMessage = messages[assistantIndex];
      if (assistantMessage?.id === this._followUpSourceMessageId && this.followUpSuggestions.length) {
        return;
      }

      const userMessage = [...messages.slice(0, assistantIndex)]
        .reverse()
        .find((message) => message?.role === 'user');

      this.applyFollowUpSuggestions(
        assistantMessage?.content || '',
        userMessage?.content || '',
        assistantMessage?.id ?? null,
      );
    },

    useSuggestion(text) {
      axonUseFollowUpSuggestion.call(this, text);
    },
  };
}

window.axonChatFollowUpsMixin = axonChatFollowUpsMixin;
