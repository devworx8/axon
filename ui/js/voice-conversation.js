/* =============================================================
   Axon - Voice Conversation Runtime
   Conversational turn-taking, text fallback dock, and cinematic
   terminal/mission overlays for the voice command center.
   ============================================================= */
function axonVoiceConversationMixin() {
  const phaseToneMap = {
    observe: 'slate',
    plan: 'cyan',
    execute: 'amber',
    verify: 'emerald',
    recover: 'rose',
  };
  const trimText = (value = '') => String(value || '').trim();
  const escapeHtml = (value = '') => String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const phaseLabel = (value = 'observe') => {
    const normalized = trimText(value).toLowerCase() || 'observe';
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  };
  const renderResponsePreview = (ctx, value = '') => {
    const text = trimText(value);
    if (!text) return '';
    if (typeof ctx.renderMd === 'function') {
      try { return ctx.renderMd(text); } catch (_) {}
    }
    return escapeHtml(text).replace(/\n/g, '<br>');
  };

  const sessionLabel = (session = null) => trimText(
    session?.title
    || session?.active_command
    || session?.cwd
    || 'Terminal',
  );

  const isTerminalRunning = (session = null) => {
    if (!session || typeof session !== 'object') return false;
    if (session.running) return true;
    return trimText(session.status).toLowerCase() === 'running';
  };

  const mapTerminalLine = (event = {}) => {
    const eventType = trimText(event.event_type).toLowerCase();
    const content = trimText(event.content || event.summary || '');
    if (!eventType && !content) return '';
    if (eventType === 'output') return content || '[output]';
    if (eventType === 'command') return content.startsWith('$ ') ? content : `$ ${content}`;
    if (eventType === 'error') return `! ${content || 'Command failed'}`;
    if (eventType === 'approval') return `? ${content || 'Approval required'}`;
    if (eventType === 'status') return `# ${content || 'Status update'}`;
    return `[${eventType || 'event'}] ${content}`.trim();
  };

  const approvalDetail = (ctx) => {
    if (ctx.terminal?.approvalRequired) {
      const command = trimText(ctx.terminal.pendingCommand || ctx.terminal.command);
      return command
        ? `Terminal approval required before Axon can run:\n${command}`
        : 'Terminal approval required before Axon can continue.';
    }
    const pending = typeof ctx.currentPendingAgentApproval === 'function'
      ? ctx.currentPendingAgentApproval()
      : null;
    if (pending) {
      const actionType = trimText(pending.action?.action_type).toLowerCase();
      const actionPath = trimText(pending.action?.path);
      if (actionType.startsWith('file_') && actionPath) {
        const operation = trimText(pending.action?.operation || actionType.replace(/^file_/, '')).replace(/_/g, ' ');
        return [
          `Approve ${operation || 'file'} access for:`,
          actionPath,
          'Axon will continue once you approve this exact path.',
        ].join('\n\n');
      }
      const detail = [
        trimText(pending.message || pending.summary || 'Agent approval required before Axon can continue.'),
        trimText(pending.commandPreview),
      ].filter(Boolean);
      return detail.join('\n\n');
    }
    return '';
  };

  return {
    ensureVoiceConversationState() {
      if (!this.voiceConversation || typeof this.voiceConversation !== 'object') {
        this.voiceConversation = {};
      }
      this.voiceConversation = {
        textDockOpen: false,
        textDraft: '',
        handsFree: true,
        awaitingReply: false,
        awaitingReplySince: '',
        awaitingReplySource: '',
        lastReplyPreview: '',
        lastCommand: '',
        terminalPinned: true,
        quickPrompts: [
          'Run a quick health check for this workspace',
          'Summarize what you are doing right now',
          'Open the terminal and show the active command',
        ],
        ...this.voiceConversation,
      };
    },

    closeVoiceConversationRuntime() {
      clearTimeout(this._voiceAwaitingReplyTimer);
      clearTimeout(this._voiceHandsFreeResumeTimer);
      this._voiceAwaitingReplyTimer = null;
      this._voiceHandsFreeResumeTimer = null;
      this.clearVoiceAwaitingReply?.();
      if (this.hudTerminalVisible) this.hudHideTerminal?.();
      if (this.hudApprovalPending) this.hudDismissApproval?.();
      if (this.voiceConversation?.textDockOpen) {
        this.voiceConversation.textDockOpen = false;
      }
    },

    voiceTextDockLabel() {
      if (trimText(this.voiceTranscript)) return 'Transcript ready';
      if (trimText(this.chatInput)) return 'Composer ready';
      return 'Fallback text command';
    },

    voiceTextDockPlaceholder() {
      if (this.voiceActive) return 'Microphone is live. You can still type here.';
      return 'Type a command for Axon when voice is unavailable...';
    },

    voiceQuickPrompts() {
      this.ensureVoiceConversationState();
      const prompts = Array.isArray(this.voiceConversation.quickPrompts)
        ? [...this.voiceConversation.quickPrompts]
        : [];
      const command = trimText(this.dashboardLiveTerminalSession?.()?.active_command);
      if (command) prompts.unshift(`Explain the active command: ${command}`);
      const workspaceName = trimText(this.chatProject?.name);
      if (workspaceName) prompts.unshift(`Give me a status update on ${workspaceName}`);
      return prompts.slice(0, 4);
    },

    syncVoiceTextDraftFromActiveInput() {
      this.ensureVoiceConversationState();
      const draft = trimText(this.voiceConversation.textDraft);
      if (draft) return draft;
      this.voiceConversation.textDraft = trimText(this.voiceTranscript || this.chatInput || '');
      return this.voiceConversation.textDraft;
    },

    toggleVoiceTextDock(force = null) {
      this.ensureVoiceConversationState();
      const next = typeof force === 'boolean' ? force : !this.voiceConversation.textDockOpen;
      this.voiceConversation.textDockOpen = next;
      if (next) {
        this.syncVoiceTextDraftFromActiveInput();
        requestAnimationFrame(() => {
          try { this.$refs.voiceTextDockInput?.focus?.(); } catch (_) {}
        });
      }
    },

    primeVoiceTextDock(value = '') {
      this.ensureVoiceConversationState();
      this.voiceConversation.textDraft = trimText(value);
      this.toggleVoiceTextDock(true);
    },

    applyVoiceQuickPrompt(prompt = '') {
      const next = trimText(prompt);
      if (!next) return;
      this.ensureVoiceConversationState();
      this.voiceConversation.textDraft = next;
      this.syncVoiceTranscript?.(next);
      this.toggleVoiceTextDock(true);
    },

    clearVoiceTextDock(resetTranscript = false) {
      this.ensureVoiceConversationState();
      this.voiceConversation.textDraft = '';
      if (resetTranscript) this.clearVoiceTranscript?.();
    },

    /** Tab-key autocomplete: fill from quick prompts or last command */
    voiceTextDockAutocomplete() {
      this.ensureVoiceConversationState();
      const draft = String(this.voiceConversation.textDraft || '').trim().toLowerCase();
      if (!draft) return;
      const prompts = this.voiceQuickPrompts?.() || [];
      const match = prompts.find(p => p.toLowerCase().startsWith(draft));
      if (match) {
        this.voiceConversation.textDraft = match;
        return;
      }
      const lastCmd = String(this.voiceConversation.lastCommand || '').trim();
      if (lastCmd && lastCmd.toLowerCase().startsWith(draft)) {
        this.voiceConversation.textDraft = lastCmd;
      }
    },

    async submitVoiceTextDock() {
      this.ensureVoiceConversationState();
      const text = trimText(this.voiceConversation.textDraft || this.voiceTranscript || this.chatInput);
      if (!text) return false;
      if (typeof this.syncVoiceTranscript === 'function') this.syncVoiceTranscript(text);
      else {
        this.voiceTranscript = text;
        this.chatInput = text;
      }

      let dispatched = false;
      if (typeof this.dispatchVoiceCommand === 'function') dispatched = await this.dispatchVoiceCommand(text);
      else if (typeof this.sendVoiceCommand === 'function') {
        await this.sendVoiceCommand(text);
        dispatched = true;
      }

      if (dispatched !== false) this.voiceConversation.textDockOpen = false;
      return dispatched !== false;
    },

    voiceMissionTimeline() {
      const operatorEntries = this.voiceLiveOperatorHistory(8).slice().reverse();
      const fallbackEntries = operatorEntries.length
        ? operatorEntries
        : (typeof this.dashboardLiveEntries === 'function' ? this.dashboardLiveEntries() : []);
      return fallbackEntries.slice(0, 6).map((entry, index) => ({
        id: entry.id || `${entry.phase || 'observe'}-${index}`,
        phase: trimText(entry.phase || 'observe').toLowerCase() || 'observe',
        title: trimText(entry.title || 'Timeline update'),
        detail: trimText(entry.detail || ''),
        at: trimText(entry.at || entry.created_at || ''),
      }));
    },

    voiceMissionTone(phase = 'observe') {
      return phaseToneMap[trimText(phase).toLowerCase()] || 'slate';
    },

    voiceMissionSummary() {
      const current = this.voiceMissionTimeline()[0] || null;
      if (!current) return 'No live mission yet';
      return `${current.title}${current.detail ? ` - ${current.detail}` : ''}`;
    },

    voiceLiveOperatorHistory(limit = 10) {
      const feed = Array.isArray(this.liveOperatorFeed) ? this.liveOperatorFeed : [];
      return feed.slice(-Math.max(1, limit));
    },

    voiceLiveOperatorFeedHtml() {
      const steps = this.voiceLiveOperatorHistory(10);
      if (!steps.length) return '';
      const latestStep = steps[steps.length - 1] || {};
      const message = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : [...(Array.isArray(this.chatMessages) ? this.chatMessages : [])].reverse().find((item) => item?.role === 'assistant');
      const draft = trimText(message?.content);
      const phase = phaseLabel(this.liveOperator?.phase || latestStep.phase || 'observe');
      const updatedAt = trimText(this.liveOperator?.updatedAt || latestStep.at || '');
      const updatedLabel = updatedAt && typeof this.timeAgo === 'function' ? this.timeAgo(updatedAt) : '';
      const lines = steps.map((entry, index) => {
        const latest = index === steps.length - 1;
        const detail = trimText(entry.detail);
        const stamp = trimText(entry.at || entry.created_at);
        const stampLabel = stamp && typeof this.timeAgo === 'function' ? this.timeAgo(stamp) : '';
        return `<div class="voice-step ${latest ? 'voice-step--latest' : 'voice-step--past'}" style="animation-delay:${index * 0.06}s">`
          + `<div class="voice-step__row">`
          + `<span class="voice-step__phase voice-step__phase--${escapeHtml(trimText(entry.phase || 'observe').toLowerCase())}">${escapeHtml(phaseLabel(entry.phase || 'observe'))}</span>`
          + `<span class="voice-step__title">${escapeHtml(entry.title || 'Working')}</span>`
          + (stampLabel ? `<span class="voice-step__meta">${escapeHtml(stampLabel)}</span>` : '')
          + `</div>`
          + (detail ? `<div class="voice-step__detail">${escapeHtml(detail)}</div>` : '')
          + `</div>`;
      }).join('');
      const draftHtml = draft
        ? `<div class="voice-agent-feed__draft">`
          + `<div class="voice-agent-feed__draft-label">Draft reply</div>`
          + `<div class="voice-agent-feed__draft-body">${renderResponsePreview(this, draft)}</div>`
          + `</div>`
        : '';
      return `<div class="voice-agent-feed">`
        + `<div class="voice-agent-feed__header">`
        + `<span class="voice-agent-feed__dot"></span>`
        + `<span>Live execution</span>`
        + `<span class="voice-agent-feed__meta">${escapeHtml(`${steps.length} steps · ${phase}${updatedLabel ? ` · ${updatedLabel}` : ''}`)}</span>`
        + `</div>`
        + `<div class="voice-agent-feed__stack">${lines}</div>`
        + draftHtml
        + `</div>`;
    },

    voiceTerminalSession() {
      return this.dashboardLiveTerminalSession?.()
        || this.dashboardLiveTerminalDetail?.()
        || this.currentTerminalSession?.()
        || this.terminal?.sessionDetail
        || null;
    },

    voiceTerminalEvents(limit = 10) {
      const detail = this.dashboardLiveTerminalDetail?.()
        || this.terminal?.liveSessionDetail
        || this.terminal?.sessionDetail
        || null;
      const events = Array.isArray(detail?.recent_events) ? detail.recent_events : [];
      return events.slice(-Math.max(1, limit));
    },

    voiceTerminalLines(limit = 10) {
      return this.voiceTerminalEvents(limit)
        .map(mapTerminalLine)
        .filter(Boolean);
    },

    voiceOperatorTraceLines(limit = 12) {
      return Array.isArray(this.hudOperatorTraceLines)
        ? this.hudOperatorTraceLines.slice(-Math.max(1, limit))
        : [];
    },

    voiceOperatorTraceTitle() {
      return trimText(this.hudOperatorTraceTitle || this.liveOperator?.title || 'Live operator telemetry');
    },

    voiceTerminalStatusLabel() {
      const session = this.voiceTerminalSession();
      if (!session) return 'Terminal idle';
      if (this.terminal?.approvalRequired) return 'Approval required';
      if (isTerminalRunning(session)) return 'Streaming live terminal output';
      return trimText(session.status || 'ready').replace(/[_-]+/g, ' ');
    },

    voiceConversationStatusLabel() {
      this.ensureVoiceConversationState();
      if (!this.showVoiceOrb) return '';
      if (this.voiceConversation.awaitingReply) return 'Awaiting your follow-up';
      if (this.voiceConversation.textDockOpen) return 'Text command dock online';
      return '';
    },

    voiceConversationStatusDetail() {
      this.ensureVoiceConversationState();
      if (!this.showVoiceOrb) return '';
      if (this.voiceConversation.awaitingReply) {
        if (this.voiceConversation.handsFree && this.voiceInputAvailable?.()) {
          return 'Axon is holding the floor open and can resume listening automatically.';
        }
        return 'Reply naturally, tap the orb again, or use the text command dock.';
      }
      if (this.voiceConversation.textDockOpen) {
        return 'Type here without leaving voice mode. The transcript panel mirrors this draft until you send it.';
      }
      return '';
    },

    voiceConversationStateCaption() {
      this.ensureVoiceConversationState();
      if (this.voiceConversation.awaitingReply) return 'Awaiting reply';
      if (this.voiceConversation.textDockOpen) return 'Text channel armed';
      return '';
    },

    clearVoiceAwaitingReply() {
      this.ensureVoiceConversationState();
      clearTimeout(this._voiceAwaitingReplyTimer);
      clearTimeout(this._voiceHandsFreeResumeTimer);
      this._voiceAwaitingReplyTimer = null;
      this._voiceHandsFreeResumeTimer = null;
      this.voiceConversation.awaitingReply = false;
      this.voiceConversation.awaitingReplySince = '';
      this.voiceConversation.awaitingReplySource = '';
    },

    armVoiceAwaitingReply(source = 'spoken') {
      this.ensureVoiceConversationState();
      if (!this.showVoiceOrb || this.reactorAsleep) return;
      this.clearVoiceAwaitingReply();
      this.voiceConversation.awaitingReply = true;
      this.voiceConversation.awaitingReplySince = new Date().toISOString();
      this.voiceConversation.awaitingReplySource = trimText(source || 'spoken') || 'spoken';
      this._voiceAwaitingReplyTimer = setTimeout(() => {
        this.clearVoiceAwaitingReply();
      }, 12000);
      this._voiceAwaitingReplyTimer?.unref?.();
      if (this.voiceConversation.handsFree && this.voiceInputAvailable?.()) {
        this._voiceHandsFreeResumeTimer = setTimeout(async () => {
          if (!this.showVoiceOrb || this.reactorAsleep || this.chatLoading || this.voiceActive) return;
          if (this.voiceSpeechBusy?.()) return;
          try {
            await this.startVoice?.();
          } catch (_) {}
        }, 1250);
        this._voiceHandsFreeResumeTimer?.unref?.();
      }
    },

    onVoiceCommandDispatched(text = '') {
      this.ensureVoiceConversationState();
      this.clearVoiceAwaitingReply();
      this.voiceConversation.lastCommand = trimText(text);
    },

    onVoiceResponseReady(text = '') {
      this.ensureVoiceConversationState();
      const preview = trimText(text).slice(0, 220);
      if (preview) this.voiceConversation.lastReplyPreview = preview;
      if (!this.showVoiceOrb || this.chatLoading) return;
      if (!(this.voiceMode && this.speechOutputSupported)) {
        this.armVoiceAwaitingReply('text');
      }
    },

    onVoiceReplyPlaybackStarted(text = '') {
      this.ensureVoiceConversationState();
      this.clearVoiceAwaitingReply();
      const preview = trimText(text).slice(0, 220);
      if (preview) this.voiceConversation.lastReplyPreview = preview;
    },

    onVoiceReplyPlaybackComplete(text = '') {
      this.ensureVoiceConversationState();
      const preview = trimText(text).slice(0, 220);
      if (preview) this.voiceConversation.lastReplyPreview = preview;
      this.armVoiceAwaitingReply('spoken');
    },

    voiceApprovalLabel() {
      if (this.terminal?.approvalRequired) return 'Allow command';
      const pending = this.currentPendingAgentApproval?.();
      if (String(pending?.action?.action_type || '').trim().toLowerCase().startsWith('file_')) {
        return 'Allow once';
      }
      if (pending) return 'Allow once';
      return 'Allow';
    },

    voiceApprovalSummary() {
      if (this.terminal?.approvalRequired) {
        return 'Axon paused before executing a guarded terminal command. Explicit permission is required to continue.';
      }
      const pending = this.currentPendingAgentApproval?.();
      if (String(pending?.action?.action_type || '').trim().toLowerCase().startsWith('file_')) {
        return 'Axon paused before inspecting a file or folder outside the current workspace. Please approve or deny the access request.';
      }
      if (pending) {
        return 'Axon paused before continuing an approval-gated task. Please approve or deny the request.';
      }
      return 'Axon needs your permission to proceed.';
    },

    async approveVoiceCenterAction(scope = 'once') {
      if (this.terminal?.approvalRequired) {
        await this.executeTerminalCommand?.(true);
        this.syncVoiceCommandCenterRuntime?.();
        return;
      }
      const pending = this.currentPendingAgentApproval?.();
      if (!pending) return;
      const ok = await this.approvePendingAgentAction?.(scope);
      if (ok) this.syncVoiceCommandCenterRuntime?.();
    },

    denyVoiceCenterAction() {
      if (this.terminal?.approvalRequired) {
        this.terminal.pendingCommand = '';
        this.terminal.approvalRequired = false;
        this.hudDismissApproval?.();
        this.showToast?.('Terminal command dismissed');
        this.syncVoiceCommandCenterRuntime?.();
        return;
      }
      if (this.currentPendingAgentApproval?.()) {
        this.dismissPendingAgentApproval?.();
        this.hudDismissApproval?.();
        this.showToast?.('Approval request dismissed');
        this.syncVoiceCommandCenterRuntime?.();
      }
    },

    syncVoiceCommandCenterRuntime() {
      this.ensureVoiceConversationState();
      if (!this.showVoiceOrb) return;

      const session = this.voiceTerminalSession();
      const lines = session ? this.voiceTerminalLines(12) : this.voiceOperatorTraceLines(12);
      const wantsInteractiveShell = !!this.interactiveTerminalPreferred?.('voice');
      const shouldShowTerminal = session
        ? !!(
          isTerminalRunning(session)
          || this.voiceConversation.terminalPinned
          || this.terminal?.approvalRequired
        )
        : !!((lines.length || wantsInteractiveShell) && (
          this.liveOperator?.active
          || this.chatLoading
          || this.voiceConversation.terminalPinned
        ));
      if (shouldShowTerminal) {
        const title = session
          ? `${sessionLabel(session)}${this.voiceTerminalStatusLabel() ? ` - ${this.voiceTerminalStatusLabel()}` : ''}`
          : this.voiceOperatorTraceTitle();
        this.hudShowTerminal?.(title, lines);
      } else if (this.hudTerminalVisible) {
        this.hudHideTerminal?.();
      }

      const detail = approvalDetail(this);
      if (detail) this.hudShowApproval?.(detail);
      else if (this.hudApprovalPending) this.hudDismissApproval?.();

      const provider = trimText(this.consoleProviderIdentity?.().providerLabel);
      const speechBusy = this.voiceSpeechBusy?.() || false;
      if (provider && (this.chatLoading || this.voiceActive || speechBusy)) {
        this.hudShowBeam?.(provider);
      } else if (!this.chatLoading && !this.voiceActive && !speechBusy) {
        this.hudHideBeam?.();
      }
    },
  };
}

window.axonVoiceConversationMixin = axonVoiceConversationMixin;
