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

  const parseArgsObject = (value = '') => {
    const text = trimText(value);
    if (!text.startsWith('{') || !text.endsWith('}')) return {};
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  };

  const fallbackWorkingArgs = (ctx, operator = {}) => {
    const args = { ...parseArgsObject(operator?.detail || '') };
    const command = trimText(typeof ctx.voiceOperatorActiveCommand === 'function' ? ctx.voiceOperatorActiveCommand() : '');
    const cwd = trimText(
      ctx.dashboardLiveTerminalSession?.()?.cwd
      || ctx.dashboardLiveTerminalDetail?.()?.cwd
      || ctx.currentTerminalSession?.()?.cwd
      || ctx.terminal?.sessionDetail?.cwd
      || operator?.filePath
      || ctx.chatProject?.path
      || ''
    );
    if (command && !args.cmd && !args.command && !args.path) args.cmd = command;
    if (cwd && !args.cwd) args.cwd = cwd;
    return args;
  };

  const statefulLiveReply = (ctx, message = null) => {
    const direct = trimText(message?.content || '');
    if (direct) return direct;
    if (typeof ctx?.voiceLatestResponseText === 'function') {
      return trimText(ctx.voiceLatestResponseText(1200));
    }
    return '';
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
      const operator = this.liveOperator || {};
      const active = !!(
        message?.streaming
        || this.chatLoading
        || operator?.active
        || this.currentWorkspaceRunActive?.()
      );
      const liveReply = trimText(
        statefulLiveReply(this, message)
      );
      const thinkingBlocks = Array.isArray(message?.thinkingBlocks) ? message.thinkingBlocks : [];
      const workingBlocks = Array.isArray(message?.workingBlocks) ? message.workingBlocks : [];
      if ((thinkingBlocks.length || workingBlocks.length || liveReply) || !active) {
        return {
          message,
          thinkingBlocks,
          workingBlocks,
          liveReply,
        };
      }

      const phase = trimText(operator?.phase).toLowerCase() || 'observe';
      const detail = trimText(operator?.detail || '');
      const stamp = trimText(operator?.updatedAt || operator?.startedAt || '');
      if (phase === 'plan' || phase === 'observe') {
        return {
          message,
          thinkingBlocks: [{
            id: 'operator-plan-fallback',
            title: trimText(operator?.title || 'Thinking'),
            content: detail || 'Axon is analysing the request and forming a plan.',
            status: active ? 'active' : 'done',
            updatedAt: stamp,
            createdAt: stamp,
          }],
          workingBlocks: [],
          liveReply,
        };
      }
      const operatorArgs = fallbackWorkingArgs(this, operator);
      const detailArgs = parseArgsObject(detail);
      return {
        message,
        thinkingBlocks: [],
        workingBlocks: [{
          id: 'operator-work-fallback',
          title: trimText(operator?.title || 'Working'),
          args: operatorArgs,
          result: detail && !Object.keys(detailArgs).length ? detail : 'Axon is executing the current step.',
          status: phase === 'recover' ? 'done' : 'running',
          updatedAt: stamp,
          createdAt: stamp,
        }],
        liveReply,
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
      const liveReply = trimText(state?.liveReply || state?.message?.content || '');
      if (!thinkingBlocks.length && !workingBlocks.length && !liveReply) return '';

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

      const replyHtml = liveReply
        ? `<div class="console-working-block console-working-block-running rounded-2xl px-3 py-2.5">`
          + `<div class="flex items-center gap-2">`
          + `<span class="console-working-chip console-working-chip-running rounded-full px-2 py-0.5 text-[9px] uppercase tracking-[0.16em]">Reply</span>`
          + `<span class="text-[11px] font-medium text-slate-100">Streaming response</span>`
          + `</div>`
          + `<div class="console-working-result mt-2 whitespace-pre-wrap">${escapeHtml(liveReply)}</div>`
          + `</div>`
        : '';

      return `<div class="voice-stream-blocks">`
        + `<div class="voice-stream-blocks__header">`
        + `<span class="voice-stream-blocks__dot"></span>`
        + `<span>Streaming blocks</span>`
        + `</div>`
        + (thinkingHtml ? `<div class="console-thinking-stack space-y-2">${thinkingHtml}</div>` : '')
        + (workingHtml ? `<div class="console-working-stack space-y-2">${workingHtml}</div>` : '')
        + replyHtml
        + `</div>`;
    },
  };
}

window.axonVoiceStreamBlocksMixin = axonVoiceStreamBlocksMixin;
