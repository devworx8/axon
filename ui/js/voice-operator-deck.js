/* =============================================================
   Axon - Voice Operator Deck Runtime
   Rich task-mode telemetry, blocker states, and command-deck UX.
   ============================================================= */
function axonVoiceOperatorDeckMixin() {
  const OPERATOR_DECK_HOLD_MS = 3200;
  const RECENT_OPERATOR_FEED_MS = 6000;
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
  const extractGoalFromFeed = (feed = []) => {
    for (const entry of feed) {
      const detail = trimText(entry?.detail || '');
      if (detail.toLowerCase().startsWith('goal received:')) {
        return trimText(detail.replace(/^goal received:\s*/i, ''));
      }
    }
    return '';
  };
  const latestCommandEvent = (events = []) => {
    const reversed = [...events].reverse();
    return reversed.find((event) => trimText(event?.event_type).toLowerCase() === 'command' && trimText(event?.content));
  };
  const hasStreamingBlocks = (ctx) => {
    const message = typeof ctx.latestAssistantMessage === 'function' ? ctx.latestAssistantMessage() : null;
    return !!(message?.streaming && ((message?.thinkingBlocks || []).length || (message?.workingBlocks || []).length));
  };
  const hasActiveAgentStream = (ctx) => {
    const message = typeof ctx.latestAssistantMessage === 'function' ? ctx.latestAssistantMessage() : null;
    return !!(message?.streaming && trimText(message?.mode).toLowerCase() === 'agent');
  };
  const hasRecentOperatorFeed = (ctx) => {
    const feed = Array.isArray(ctx.liveOperatorFeed) ? ctx.liveOperatorFeed : [];
    const latest = feed[feed.length - 1];
    if (!latest) return false;
    const stamp = Date.parse(String(latest.at || ''));
    if (!Number.isFinite(stamp)) return true;
    return (Date.now() - stamp) <= RECENT_OPERATOR_FEED_MS;
  };
  const sessionRunning = (session = null) => {
    if (!session || typeof session !== 'object') return false;
    if (session.running) return true;
    const status = trimText(session.status).toLowerCase();
    return status === 'running' || status === 'approval_required';
  };
  const activeAutoSession = (ctx) => {
    const session = typeof ctx.currentWorkspaceAutoSession === 'function' ? ctx.currentWorkspaceAutoSession() : null;
    return sessionRunning(session) ? session : null;
  };
  const approvalDetail = (ctx) => {
    if (ctx.terminal?.approvalRequired) {
      const command = trimText(ctx.terminal.pendingCommand || ctx.terminal.command);
      return command
        ? `Terminal approval required before Axon can run: ${command}`
        : 'Terminal approval required before Axon can continue.';
    }
    const pending = typeof ctx.currentPendingAgentApproval === 'function'
      ? ctx.currentPendingAgentApproval()
      : null;
    if (!pending) return '';
    const actionType = trimText(pending.action?.action_type).toLowerCase();
    const path = trimText(pending.action?.path);
    if (actionType.startsWith('file_') && path) {
      return `File access approval required for ${path}.`;
    }
    return trimText(pending.message || pending.summary || 'Agent approval required before Axon can continue.');
  };
  const detectOperationalIntent = (value = '') => {
    const text = trimText(value);
    const lower = text.toLowerCase();
    if (!text) return { active: false, key: '', label: '', score: 0 };
    const intents = [
      { key: 'deploy', label: 'Deploy', patterns: ['deploy', 'release', 'publish', 'ship', 'eas', 'expo build', 'build apk', 'build ios'] },
      { key: 'build', label: 'Build', patterns: ['build', 'compile', 'bundle', 'package', 'assemble'] },
      { key: 'test', label: 'Test', patterns: ['test', 'typecheck', 'lint', 'verify', 'smoke test', 'pytest', 'unit test'] },
      { key: 'debug', label: 'Debug', patterns: ['debug', 'diagnose', 'investigate', 'why is', 'check why', 'fix the error', 'not working'] },
      { key: 'git', label: 'Git', patterns: ['git ', 'commit', 'branch', 'diff', 'status', 'push', 'pull', 'merge', 'rebase'] },
      { key: 'inspect', label: 'Inspect', patterns: ['inspect', 'scan', 'check', 'open', 'show', 'find', 'search', 'look at', 'status of'] },
    ];
    let best = { active: false, key: '', label: '', score: 0 };
    for (const intent of intents) {
      const score = intent.patterns.reduce((sum, pattern) => sum + (lower.includes(pattern) ? 1 : 0), 0);
      if (score > best.score) best = { active: score > 0, key: intent.key, label: intent.label, score };
    }
    if (!best.active && /(^|\s)(eas\.json|app\.json|package\.json|metro\.config|gradle|podfile|expo)/i.test(text)) {
      return { active: true, key: 'inspect', label: 'Inspect', score: 1 };
    }
    return best;
  };
  const blockerReason = (ctx) => {
    const approval = approvalDetail(ctx);
    if (approval) {
      return {
        title: 'Approval blocked',
        detail: approval,
        action: 'Approve or deny the pending action so Axon can continue.',
      };
    }
    const mismatch = typeof ctx.currentWorkspaceRunMismatch === 'function'
      ? ctx.currentWorkspaceRunMismatch()
      : null;
    if (mismatch) {
      return {
        title: 'Workspace mismatch',
        detail: `Axon started this run in ${mismatch.reportedLabel}, not ${mismatch.expectedLabel}.`,
        action: `Switch to ${mismatch.reportedLabel} or restart the task in ${mismatch.expectedLabel}.`,
      };
    }
    const latestText = trimText(typeof ctx.voiceLatestResponseText === 'function' ? ctx.voiceLatestResponseText(700) : '');
    const latestLower = latestText.toLowerCase();
    if (latestLower.includes('credit balance is too low')) {
      return {
        title: 'Provider credits depleted',
        detail: 'Anthropic credits are exhausted for this request path.',
        action: 'Switch to the local qwen backend or top up the provider before retrying.',
      };
    }
    if (latestLower.includes('agent mode requires the ollama backend')) {
      return {
        title: 'Agent backend unavailable',
        detail: 'Agent mode is not available on the current backend.',
        action: 'Switch back to the local Ollama runtime before retrying the task.',
      };
    }
    if (trimText(ctx.liveOperator?.phase).toLowerCase() === 'recover' && trimText(ctx.liveOperator?.detail)) {
      return {
        title: 'Operator blocked',
        detail: trimText(ctx.liveOperator.detail),
        action: 'Review the blocker and retry once the dependency is available.',
      };
    }
    return null;
  };

  return {
    ensureVoiceOperatorDeckState() {
      this.ensureVoiceConversationState?.();
      if (!this.voiceConversation || typeof this.voiceConversation !== 'object') {
        this.voiceConversation = {};
      }
      if (typeof this.voiceConversation?.terminalPinnedTouched !== 'boolean') {
        this.voiceConversation.terminalPinnedTouched = false;
        this.voiceConversation.terminalPinned = false;
      }
      if (!this.voiceOperatorDeck || typeof this.voiceOperatorDeck !== 'object') {
        this.voiceOperatorDeck = {};
      }
      const holdUntil = Number(this.voiceOperatorDeck.holdUntil || 0);
      this.voiceOperatorDeck = {
        holdUntil: Number.isFinite(holdUntil) ? holdUntil : 0,
      };
    },
    voiceOperationalIntent(commandText = '') {
      this.ensureVoiceOperatorDeckState();
      return detectOperationalIntent(
        commandText
        || this.voiceConversation?.textDraft
        || this.voiceConversation?.lastCommand
        || this.voiceTranscript
        || this.chatInput,
      );
    },
    voiceOperationalIntentActive(commandText = '') {
      return !!this.voiceOperationalIntent(commandText).active;
    },

    voiceShouldRenderOperatorDeck() {
      this.ensureVoiceOperatorDeckState();
      const activeNow = !!(
        this.chatLoading
        || this.currentWorkspaceRunActive?.()
        || this.liveOperator?.active
        || activeAutoSession(this)
        || this.voiceOperatorBlocker()
        || this.voiceOperatorActiveCommand()
        || hasStreamingBlocks(this)
        || hasActiveAgentStream(this)
        || hasRecentOperatorFeed(this)
      );
      if (activeNow) {
        this.voiceOperatorDeck.holdUntil = Date.now() + OPERATOR_DECK_HOLD_MS;
        return true;
      }
      return Number(this.voiceOperatorDeck?.holdUntil || 0) > Date.now();
    },

    voiceResponsePanelLabel() {
      return this.voiceShouldRenderOperatorDeck() ? 'Operator deck' : 'Response';
    },

    voiceResponsePanelToneClass() {
      return this.voiceShouldRenderOperatorDeck() ? 'voice-float--operator' : '';
    },

    voiceOperatorGoal() {
      const draft = trimText(this.voiceConversation?.textDraft);
      const lastCommand = trimText(this.voiceConversation?.lastCommand);
      const feedGoal = extractGoalFromFeed(Array.isArray(this.liveOperatorFeed) ? this.liveOperatorFeed : []);
      const autoSession = activeAutoSession(this);
      const liveGoal = trimText(this.liveOperator?.summary || this.liveOperator?.detail || this.liveOperator?.title);
      return feedGoal || liveGoal || trimText(autoSession?.title || autoSession?.detail) || draft || lastCommand || 'Awaiting command';
    },

    voiceOperatorPhase() {
      const blocker = this.voiceOperatorBlocker();
      if (blocker) return 'recover';
      const phase = trimText(this.liveOperator?.phase).toLowerCase();
      if (phase) return phase;
      return activeAutoSession(this) || hasStreamingBlocks(this) ? 'execute' : 'observe';
    },

    voiceOperatorTone() {
      return phaseToneMap[this.voiceOperatorPhase()] || 'slate';
    },

    voiceOperatorScope() {
      return trimText(
        this.dashboardLiveSurfaceScopeLabel?.()
        || this.chatProject?.name
        || this.chatProject?.path
        || 'Current workspace',
      );
    },

    voiceOperatorActiveCommand() {
      const session = this.dashboardLiveTerminalSession?.()
        || this.dashboardLiveTerminalDetail?.()
        || this.currentTerminalSession?.()
        || this.terminal?.sessionDetail
        || null;
      const active = trimText(session?.active_command);
      if (active) return active;
      const event = latestCommandEvent(this.voiceTerminalEvents?.(8) || []);
      const content = trimText(event?.content);
      return content.startsWith('$ ') ? content.slice(2) : content;
    },

    voiceOperatorBlocker() {
      return blockerReason(this);
    },

    voiceTerminalSessionActive() {
      const session = this.voiceTerminalSession?.();
      return !!(
        trimText(session?.active_command)
        || sessionRunning(session)
        || this.terminal?.approvalRequired
      );
    },

    voiceTerminalTraceActive() {
      const lines = this.voiceOperatorTraceLines?.(8) || [];
      if (!lines.length) return false;
      const title = trimText(this.hudOperatorTraceTitle || this.liveOperator?.title).toLowerCase();
      return lines.some((line) => {
        const text = trimText(line);
        return text.startsWith('$ ') || text.startsWith('@ ');
      }) || (lines.length > 0 && (title.includes('shell') || title.includes('terminal')));
    },

    voiceTerminalAutoDockActive() {
      return !!(
        this.terminal?.approvalRequired
        || this.voiceTerminalSessionActive?.()
        || (this.voiceTerminalTraceActive?.() && (this.chatLoading || this.liveOperator?.active))
      );
    },

    toggleVoiceTerminalPin() {
      this.ensureVoiceOperatorDeckState();
      this.voiceConversation.terminalPinnedTouched = true;
      this.voiceConversation.terminalPinned = !this.voiceConversation.terminalPinned;
      this.syncVoiceCommandCenterRuntime?.();
    },

    voiceOperatorHeadline() {
      const blocker = this.voiceOperatorBlocker();
      if (blocker) return blocker.title;
      if (this.chatLoading || this.liveOperator?.active) {
        return trimText(this.liveOperator?.title) || `${phaseLabel(this.voiceOperatorPhase())} in progress`;
      }
      const autoSession = activeAutoSession(this);
      if (autoSession) return trimText(autoSession.title || autoSession.detail) || 'Auto session running';
      if (this.voiceResponseAvailable?.()) return 'Response ready';
      const intent = this.voiceOperationalIntent();
      if (intent.active) return `${intent.label} ready to dispatch`;
      return 'Awaiting command';
    },

    voiceOperatorSurfaceChip() {
      const blocker = this.voiceOperatorBlocker();
      if (blocker) return blocker.title;
      if (this.voiceOperatorActiveCommand()) return 'Terminal live';
      if (this.chatLoading || this.liveOperator?.active) return `${phaseLabel(this.voiceOperatorPhase())} phase`;
      if (activeAutoSession(this)) return 'Auto running';
      const intent = this.voiceOperationalIntent();
      if (intent.active) return `${intent.label} staged`;
      return 'Standby';
    },

    voiceOperatorNextStep() {
      const blocker = this.voiceOperatorBlocker();
      if (blocker?.action) return blocker.action;
      if (this.voiceOperatorActiveCommand()) {
        return 'Watch the live terminal while Axon finishes the current command.';
      }
      if (this.chatLoading || this.liveOperator?.active) {
        return trimText(this.liveOperator?.detail) || 'Axon is lining up the next safe action.';
      }
      const autoSession = activeAutoSession(this);
      if (autoSession) {
        return trimText(autoSession.detail || autoSession.last_error) || 'Axon is still working in the sandbox.';
      }
      const intent = this.voiceOperationalIntent();
      if (intent.active) {
        return 'Send the command to start a live run.';
      }
      return 'Give Axon an operational goal or ask for a status update.';
    },

    voiceOperatorTimeline(limit = 5) {
      const feed = Array.isArray(this.liveOperatorFeed) ? this.liveOperatorFeed : [];
      if (!feed.length) return [];
      return [...feed]
        .slice(-Math.max(1, limit))
        .reverse()
        .map((entry) => ({
          id: entry.id || `${entry.at || Date.now()}-${entry.phase || 'observe'}`,
          phase: trimText(entry.phase || 'observe').toLowerCase() || 'observe',
          title: trimText(entry.title || 'Working'),
          detail: trimText(entry.detail || ''),
          at: trimText(entry.at || ''),
        }));
    },

    voiceCommandDeckTitle() {
      this.ensureVoiceOperatorDeckState();
      if (this.chatLoading || this.liveOperator?.active || activeAutoSession(this)) return 'Command deck engaged';
      const intent = this.voiceOperationalIntent();
      if (intent.active) return `${intent.label} command deck`;
      return 'Fallback text channel';
    },

    voiceCommandDeckHint() {
      this.ensureVoiceOperatorDeckState();
      const blocker = this.voiceOperatorBlocker();
      if (blocker?.action) return blocker.action;
      if (this.chatLoading || this.liveOperator?.active || activeAutoSession(this)) {
        return 'Say stop to interrupt this run, or give another instruction to steer it.';
      }
      const intent = this.voiceOperationalIntent();
      if (intent.active) {
        return 'Send the command and Axon will inspect first, then act.';
      }
      return 'Type without leaving voice mode.';
    },

    voiceCommandDeckMeta() {
      this.ensureVoiceOperatorDeckState();
      const blocker = this.voiceOperatorBlocker();
      if (blocker?.detail) return blocker.detail;
      return trimText(this.voiceConversation?.lastReplyPreview) || this.voiceOperatorNextStep();
    },

    voiceCommandDeckSubmitLabel() {
      this.ensureVoiceOperatorDeckState();
      const intent = this.voiceOperationalIntent();
      return intent.active ? 'Run task' : 'Send';
    },

    voiceTextDockLabel() {
      this.ensureVoiceOperatorDeckState();
      const blocker = this.voiceOperatorBlocker();
      if (blocker) return 'Operator blocked';
      if (this.chatLoading || this.liveOperator?.active || activeAutoSession(this) || hasStreamingBlocks(this)) return 'Run in progress';
      const intent = this.voiceOperationalIntent();
      if (intent.active) return `${intent.label} ready`;
      if (trimText(this.voiceTranscript)) return 'Transcript ready';
      if (trimText(this.chatInput)) return 'Composer ready';
      return 'Fallback text command';
    },

    voiceTextDockPlaceholder() {
      this.ensureVoiceOperatorDeckState();
      const intent = this.voiceOperationalIntent();
      if (intent.active) {
        return 'Describe the outcome you want. Axon will inspect first, then act and open the live terminal.';
      }
      if (this.voiceActive) return 'Microphone is live. You can still type here.';
      return 'Type a command for Axon when voice is unavailable...';
    },

    onVoiceCommandDispatched(text = '') {
      this.ensureVoiceOperatorDeckState();
      this.clearVoiceAwaitingReply?.();
      this.voiceConversation.lastCommand = trimText(text);
    },

    syncVoiceCommandCenterRuntime() {
      this.ensureVoiceOperatorDeckState();
      if (!this.showVoiceOrb) return;
      if (this.chatLoading || this.liveOperator?.active || activeAutoSession(this)) {
        this.clearVoiceAwaitingReply?.();
      }

      const session = this.voiceTerminalSession?.();
      const blocker = this.voiceOperatorBlocker();
      const manualTerminalPin = !!(this.voiceConversation?.terminalPinnedTouched && this.voiceConversation?.terminalPinned);
      const sessionActive = !!this.voiceTerminalSessionActive?.();
      const traceActive = !!this.voiceTerminalTraceActive?.();
      const useSessionSurface = !!(session && (manualTerminalPin || sessionActive));
      const lines = useSessionSurface ? (this.voiceTerminalLines?.(12) || []) : (this.voiceOperatorTraceLines?.(12) || []);
      const autoTerminal = !!(
        this.voiceTerminalAutoDockActive?.()
        || (blocker && this.terminal?.approvalRequired)
      );
      const shouldShowTerminal = !!(manualTerminalPin || autoTerminal);

      if (shouldShowTerminal) {
        const title = useSessionSurface
          ? `${trimText(session.title || session.active_command || session.cwd || 'Terminal')}${this.voiceTerminalStatusLabel?.() ? ` - ${this.voiceTerminalStatusLabel()}` : ''}`
          : trimText(this.hudOperatorTraceTitle || (traceActive ? this.liveOperator?.title : '') || 'Live terminal');
        this.hudShowTerminal?.(title, lines);
      } else if (this.hudTerminalVisible) {
        this.hudHideTerminal?.();
      }

      const approval = approvalDetail(this);
      if (approval) this.hudShowApproval?.(approval);
      else if (this.hudApprovalPending) this.hudDismissApproval?.();

      const provider = trimText(this.consoleProviderIdentity?.().providerLabel);
      const speechBusy = this.voiceSpeechBusy?.() || false;
      if (provider && (this.chatLoading || this.voiceActive || speechBusy)) {
        this.hudShowBeam?.(provider);
      } else if (!this.chatLoading && !this.voiceActive && !speechBusy) {
        this.hudHideBeam?.();
      }
    },

    voiceLiveOperatorFeedHtml() {
      if (!this.voiceShouldRenderOperatorDeck()) return '';
      const tone = escapeHtml(this.voiceOperatorTone());
      const goal = escapeHtml(this.voiceOperatorGoal());
      const phase = escapeHtml(phaseLabel(this.voiceOperatorPhase()));
      const chip = escapeHtml(this.voiceOperatorSurfaceChip());
      const headline = escapeHtml(this.voiceOperatorHeadline());
      const scope = escapeHtml(this.voiceOperatorScope());
      const streamBlocksHtml = typeof this.voiceStreamingBlocksHtml === 'function' ? this.voiceStreamingBlocksHtml() : '';
      const surfacesHtml = this.voiceOperatorSurfaceCardsHtml?.() || '';
      const artifactRailHtml = this.voiceArtifactRailHtml?.() || '';
      const activityFeedHtml = this.voiceActivityFeedHtml?.(5) || '';
      const activeCommand = escapeHtml(
        this.voiceOperatorActiveCommand()
        || (streamBlocksHtml ? 'Reasoning before tool execution' : 'No shell command running yet')
      );
      const nextStep = escapeHtml(this.voiceOperatorNextStep());
      const blocker = this.voiceOperatorBlocker();
      const blockerHtml = blocker
        ? `<div class="voice-operator-deck__blocker">`
          + `<div class="voice-operator-deck__blocker-label">${escapeHtml(blocker.title)}</div>`
          + `<div class="voice-operator-deck__blocker-body">${escapeHtml(blocker.detail)}</div>`
          + `<div class="voice-operator-deck__blocker-next">${escapeHtml(blocker.action || '')}</div>`
          + `</div>`
        : '';
      const timelineHtml = this.voiceOperatorTimeline(5).map((entry, index) => (
        `<div class="voice-operator-deck__step voice-operator-deck__step--${escapeHtml(entry.phase)}" style="animation-delay:${index * 0.06}s">`
        + `<div class="voice-operator-deck__step-phase">${escapeHtml(phaseLabel(entry.phase))}</div>`
        + `<div class="voice-operator-deck__step-copy">`
        + `<div class="voice-operator-deck__step-title">${escapeHtml(entry.title)}</div>`
        + `<div class="voice-operator-deck__step-detail">${escapeHtml(entry.detail || 'Axon is staging the next action.')}</div>`
        + `</div>`
        + `</div>`
      )).join('');
      const responsePreview = !this.chatLoading && this.voiceResponseAvailable?.()
        ? `<div class="voice-operator-deck__reply"><div class="voice-operator-deck__reply-label">Latest response</div><div class="voice-operator-deck__reply-body">${renderResponsePreview(this, this.voiceLatestResponseText?.(420) || '')}</div></div>`
        : '';

      return `<div class="voice-operator-deck voice-operator-deck--${tone}">`
        + `<div class="voice-operator-deck__header">`
        + `<div>`
        + `<div class="voice-operator-deck__eyebrow">Operator deck</div>`
        + `<div class="voice-operator-deck__headline">${headline}</div>`
        + `</div>`
        + `<div class="voice-operator-deck__chips">`
        + `<span class="voice-operator-deck__chip voice-operator-deck__chip--${tone}">${phase}</span>`
        + `<span class="voice-operator-deck__chip">${chip}</span>`
        + `</div>`
        + `</div>`
        + `<div class="voice-operator-deck__grid">`
        + `<div class="voice-operator-deck__metric"><div class="voice-operator-deck__label">Goal</div><div class="voice-operator-deck__value">${goal}</div></div>`
        + `<div class="voice-operator-deck__metric"><div class="voice-operator-deck__label">Scope</div><div class="voice-operator-deck__value">${scope}</div></div>`
        + `<div class="voice-operator-deck__metric"><div class="voice-operator-deck__label">Command</div><div class="voice-operator-deck__value voice-operator-deck__value--mono">${activeCommand}</div></div>`
        + `<div class="voice-operator-deck__metric"><div class="voice-operator-deck__label">Next</div><div class="voice-operator-deck__value">${nextStep}</div></div>`
        + `</div>`
        + surfacesHtml
        + artifactRailHtml
        + streamBlocksHtml
        + blockerHtml
        + activityFeedHtml
        + `<div class="voice-operator-deck__timeline">${timelineHtml || '<div class="voice-operator-deck__empty">Axon is waiting for live execution events.</div>'}</div>`
        + responsePreview
        + `</div>`;
    },
  };
}

window.axonVoiceOperatorDeckMixin = axonVoiceOperatorDeckMixin;
