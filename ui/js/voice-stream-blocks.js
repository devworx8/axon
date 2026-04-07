/* =============================================================
   Axon - Voice Stream Blocks
   Render chat-style thinking and working blocks inside voice mode.
   ============================================================= */
function axonVoiceStreamBlocksMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const escapeHtml = (value = '') => String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const blockTimeLabel = (ctx, value = '') => {
    const stamp = trimText(value);
    if (!stamp || typeof ctx.timeAgo !== 'function') return '';
    try {
      return trimText(ctx.timeAgo(stamp));
    } catch (_) {
      return '';
    }
  };

  const renderArgs = (value = {}) => {
    if (!value || typeof value !== 'object') return '';
    const keys = Object.keys(value);
    if (!keys.length) return '';
    try {
      return escapeHtml(JSON.stringify(value));
    } catch (_) {
      return '';
    }
  };

  return {
    voiceLatestStreamMessage() {
      if (typeof this.latestAssistantMessage === 'function') {
        return this.latestAssistantMessage();
      }
      return null;
    },

    voiceStreamingBlocksState() {
      const message = this.voiceLatestStreamMessage?.();
      return {
        message,
        thinkingBlocks: Array.isArray(message?.thinkingBlocks) ? message.thinkingBlocks : [],
        workingBlocks: Array.isArray(message?.workingBlocks) ? message.workingBlocks : [],
      };
    },

    voiceStreamingBlocksAvailable() {
      const state = this.voiceStreamingBlocksState?.();
      return !!((state?.thinkingBlocks || []).length || (state?.workingBlocks || []).length);
    },

    voiceStreamingBlocksHtml() {
      const state = this.voiceStreamingBlocksState?.();
      const thinkingBlocks = state?.thinkingBlocks || [];
      const workingBlocks = state?.workingBlocks || [];
      if (!thinkingBlocks.length && !workingBlocks.length) return '';

      const thinkingHtml = thinkingBlocks.map((block) => {
        const stamp = blockTimeLabel(this, block?.updatedAt || block?.createdAt);
        return `<div class="console-thinking-block rounded-2xl px-3 py-2.5">`
          + `<div class="flex items-center gap-2">`
          + `<span class="console-thinking-chip rounded-full px-2 py-0.5 text-[9px] uppercase tracking-[0.16em]">${escapeHtml(block?.title || 'Thinking')}</span>`
          + `<span class="text-[10px] text-slate-500">${escapeHtml(stamp)}</span>`
          + `</div>`
          + `<div class="console-thinking-copy mt-2 whitespace-pre-wrap">${escapeHtml(block?.content || '')}</div>`
          + `</div>`;
      }).join('');

      const workingHtml = workingBlocks.map((block) => {
        const running = trimText(block?.status).toLowerCase() === 'running';
        const args = renderArgs(block?.args || {});
        const result = escapeHtml(String(block?.result || '').slice(0, 240));
        const stamp = blockTimeLabel(this, block?.updatedAt || block?.createdAt);
        return `<div class="${running ? 'console-working-block console-working-block-running' : 'console-working-block console-working-block-done'} rounded-2xl px-3 py-2.5">`
          + `<div class="flex items-center gap-2">`
          + `<span class="${running ? 'console-working-chip console-working-chip-running' : 'console-working-chip console-working-chip-done'} rounded-full px-2 py-0.5 text-[9px] uppercase tracking-[0.16em]">${running ? 'Working' : 'Worked'}</span>`
          + `<span class="text-[11px] font-medium text-slate-100">${escapeHtml(block?.title || 'Working')}</span>`
          + `<span class="ml-auto text-[10px] text-slate-500">${escapeHtml(stamp)}</span>`
          + `</div>`
          + (args ? `<div class="console-working-args mt-2 rounded-xl px-3 py-2 font-mono text-[10px] break-all">${args}</div>` : '')
          + (result ? `<div class="console-working-result mt-2 whitespace-pre-wrap">${result}</div>` : '')
          + `</div>`;
      }).join('');

      return `<div class="voice-stream-blocks">`
        + `<div class="voice-stream-blocks__header">`
        + `<span class="voice-stream-blocks__dot"></span>`
        + `<span>Streaming blocks</span>`
        + `</div>`
        + (thinkingHtml ? `<div class="console-thinking-stack space-y-2">${thinkingHtml}</div>` : '')
        + (workingHtml ? `<div class="console-working-stack space-y-2">${workingHtml}</div>` : '')
        + `</div>`;
    },
  };
}

window.axonVoiceStreamBlocksMixin = axonVoiceStreamBlocksMixin;
