/* ══════════════════════════════════════════════════════════════
   Axon — Voice Command Center Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceCommandCenterMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const escapeAttr = (value = '') => String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  const extractLocalPathFromHref = (href = '') => {
    const value = String(href || '').trim();
    if (!value) return '';
    try {
      const normalized = value.replace(/^https?:\/\/[^/]+/i, '');
      const [pathname, query = ''] = normalized.split('?');
      if (pathname !== '/api/files/open') return '';
      const pathEntry = query
        .split('&')
        .map(part => part.split('='))
        .find(([key]) => String(key || '').trim() === 'path');
      return decodeURIComponent(pathEntry?.[1] || '');
    } catch (_) {
      return '';
    }
  };

  const decorateVoiceResponseLinks = (html = '') => {
    return String(html || '').replace(/<a\b([^>]*)href="([^"]+)"([^>]*)>([\s\S]*?)<\/a>/gi, (match, beforeHref, href, afterHref, body) => {
      const localPath = extractLocalPathFromHref(href);
      if (!localPath) return match;
      let attrs = `${beforeHref || ''} href="${escapeAttr(href)}"${afterHref || ''}`;
      if (/class="/i.test(attrs)) {
        attrs = attrs.replace(/class="([^"]*)"/i, (_classMatch, classValue) => `class="${escapeAttr(`${classValue} voice-file-chip`.trim())}"`);
      } else {
        attrs += ' class="voice-file-chip"';
      }
      if (!/data-voice-path="/i.test(attrs)) {
        attrs += ` data-voice-path="${escapeAttr(localPath)}"`;
      }
      return `<a${attrs}>${body}</a>`;
    });
  };

  const pickBootGreeting = (ctx) => {
    if (ctx.currentWorkspaceRunActive?.() || ctx.chatLoading || ctx.liveOperator?.active) {
      const headline = trimText(ctx.voiceOperatorHeadline?.() || ctx.liveOperator?.title || 'the active task');
      const nextStep = trimText(ctx.voiceOperatorNextStep?.() || ctx.liveOperator?.detail || '');
      const busyLine = nextStep && nextStep !== headline
        ? `Resuming the active task, Sir. ${headline}. ${nextStep}`
        : `Resuming the active task, Sir. ${headline}`;
      return busyLine.slice(0, 220);
    }
    if (ctx.voiceConversation?.awaitingReply) {
      return "I'm still with you, Sir. Awaiting your next instruction.";
    }

    const hour = new Date().getHours();
    const timeWord = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
    const greetings = [
      `Good ${timeWord}, Sir. All systems are online.`,
      `Reactor online. Standing by, Sir.`,
      `Good ${timeWord}, Sir. Axon is ready for your command.`,
      `Systems nominal. How can I help you, Sir?`,
      `Online and operational. Good ${timeWord}, Sir.`,
    ];
    return greetings[Math.floor(Math.random() * greetings.length)];
  };

  const pickSleepGoodbye = () => {
    const goodbyes = [
      'Going offline, Sir. I\'ll be here when you need me.',
      'Reactor powering down. Rest well, Sir.',
      'Standing down, Sir. Systems on standby.',
    ];
    return goodbyes[Math.floor(Math.random() * goodbyes.length)];
  };

  return {

    /** Sleep state — when true the reactor goes dark */
    reactorAsleep: false,

    /** Tap the ORB: asleep → wake, awake → toggle voice listen */
    toggleReactorOrbAction() {
      if (this.reactorAsleep) {
        this.wakeReactor();
        return;
      }
      // On mobile: tap starts/stops voice listening (more intuitive)
      if (this.isMobile || window.innerWidth < 768) {
        this.startVoiceListening();
        return;
      }
      // Desktop: tap puts reactor to sleep
      this.sleepReactor();
    },

    /** Put reactor to sleep — hard-stop capture/speech, play power-down sound, then dim */
    sleepReactor() {
      this.reactorAsleep = true;
      clearTimeout(this._bootGreetingTimer);
      this._cancelNarrationQueue?.();
      this.clearVoiceAwaitingReply?.();
      if (this.voiceActive) {
        Promise.resolve(this.startVoice?.()).catch(() => {});
      }
      if (typeof this.stopSpeech === 'function') this.stopSpeech();
      if (window.axonVoiceSleepSound) {
        window.axonVoiceSleepSound.play();
      }
    },

    /** Wake reactor — re-ignite glow + boot sound */
    wakeReactor() {
      this.reactorAsleep = false;
      // Re-trigger ignite animations by removing and re-adding the class
      document.querySelectorAll('.axon-reactor').forEach(svg => {
        svg.classList.add('reactor--reignite');
        requestAnimationFrame(() => {
          svg.classList.remove('reactor--reignite');
        });
      });
      if (window.axonVoiceBootSound) {
        window.axonVoiceBootSound.play();
      }
      // JARVIS-style greeting after boot sound finishes (~6.5s)
      this._scheduleBootGreeting();
    },

    /**
     * Compatibility wrapper for isolated consumers/tests.
     * The dedicated greeting mixin overrides this in full app composition.
     */
    _scheduleBootGreeting() {
      clearTimeout(this._bootGreetingTimer);
      const delay = (this.currentWorkspaceRunActive?.() || this.chatLoading || this.liveOperator?.active) ? 520 : 6800;
      this._bootGreetingTimer = setTimeout(() => {
        if (!this.showVoiceOrb || this.reactorAsleep) return;
        const greeting = this._pickBootGreeting();
        this._speakGreeting(greeting);
        this._showGreetingToast?.(greeting);
      }, delay);
    },

    _speakGreeting(text) {
      if (typeof this.speakMessage === 'function') {
        this.speakMessage(text);
      }
    },

    _pickBootGreeting() {
      return pickBootGreeting(this);
    },

    _pickSleepGoodbye() {
      return pickSleepGoodbye();
    },

    async startVoiceListening() {
      this.clearVoiceAwaitingReply?.();
      if (this.voiceActive) {
        await this.startVoice();
        if (String(this.voiceTranscript || '').trim()) {
          await this.dispatchVoiceCommand?.();
        }
        return;
      }
      this._voiceResponseDismissedAt = 0;
      this.openVoiceCommandCenter?.();
      await this.startVoice();
    },

    async dispatchVoiceCommand(commandText = '') {
      const raw = String(commandText || this.voiceTranscript || this.chatInput || '').trim();
      const normalize = window.axonVoiceSpeech?.normalizeCommandText;
      const text = normalize ? normalize(raw) : raw;
      const workspaceBusy = typeof this.currentWorkspaceRunActive === 'function'
        ? this.currentWorkspaceRunActive()
        : !!this.chatLoading;
      if (!text) return false;

      this.syncVoiceTranscript?.(text);
      const permissionCommand = window.axonVoiceSpeech?.permissionCommand;
      if (permissionCommand) {
        const handled = await permissionCommand(text, {
          setPermissionPreset: this.setPermissionPreset?.bind(this),
          permissionPresetKey: this.permissionPresetKey?.bind(this),
        });
        if (handled) {
          this.clearVoiceTranscript?.();
          return true;
        }
      }
      if (workspaceBusy) {
        this.onVoiceCommandDispatched?.(text);
        const busyAction = await this.handleBusyWorkspaceCommand?.(text);
        if (!busyAction) {
          this.showToast?.('This workspace is already busy. Say "stop" to interrupt, or give another instruction to steer it. Switch tabs to run another workspace in parallel.');
          return false;
        }
        this.clearVoiceTranscript?.();
        return true;
      }

      await this.sendVoiceCommand?.(text);
      return true;
    },

    voiceRecordingActive() {
      return !!this.voiceActive;
    },

    voiceLatestResponseMarker() {
      const message = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : [...(Array.isArray(this.chatMessages) ? this.chatMessages : [])].reverse().find(item => item?.role === 'assistant');
      return Number(message?.id)
        || Date.parse(String(message?.created_at || ''))
        || 0;
    },

    voiceLatestResponseText(limit = 6000) {
      const message = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : [...(Array.isArray(this.chatMessages) ? this.chatMessages : [])].reverse().find(item => item?.role === 'assistant');
      const content = String(message?.content || '').trim();
      if (!content) {
        if (this.chatLoading) return String(this.liveOperator?.detail || '').trim();
        return '';
      }
      const messageMarker = this.voiceLatestResponseMarker();
      if (messageMarker && Number(this._voiceResponseDismissedAt || 0) >= messageMarker) {
        return '';
      }
      return content.slice(0, limit);
    },

    voiceTaskSurfaceActive() {
      return !!(
        this.voiceShouldRenderOperatorDeck?.()
        || (this.chatLoading && this.liveOperator?.active)
      );
    },

    voiceResponseAvailable() {
      return !!(this.voiceTaskSurfaceActive() || this.voiceLatestResponseText());
    },

    voiceDisplayTranscript() {
      const dockDraft = String(
        this.voiceConversation?.textDockOpen
          ? (this.voiceConversation?.textDraft || this.chatInput || '')
          : ''
      ).trim();
      if (dockDraft) return dockDraft;
      return String(this.voiceTranscript || '').trim() || 'Waiting for a voice command…';
    },

    voiceDisplayResponse() {
      const text = this.voiceLatestResponseText();
      if (text) {
        if (text.includes('ERROR: Access outside the allowed directories')) {
          return 'That file or folder is outside the current workspace sandbox. Ask Axon to open the exact path again and approve the file-access prompt when it appears.';
        }
        return text;
      }
      if (this.chatLoading) return 'Axon is processing your request…';
      return 'The latest voice response will appear here.';
    },

    voiceTaskSurfaceHtml() {
      const taskSurfaceActive = this.voiceTaskSurfaceActive();
      if (!taskSurfaceActive) return '';
      if (typeof this.voiceOperatorDeckHtml === 'function') {
        const html = this.voiceOperatorDeckHtml();
        if (html) return html;
      }
      if (typeof this.voiceConversationFeedHtml === 'function') {
        const html = this.voiceConversationFeedHtml();
        if (html) return html;
      }
      if (typeof this.voiceLiveOperatorFeedHtml === 'function') {
        return this.voiceLiveOperatorFeedHtml() || '';
      }
      return '';
    },

    voiceResponseRenderClass() {
      return this.voiceTaskSurfaceActive() ? '' : 'voice-response-render';
    },

    /** Render response as HTML with markdown + file path chips */
    voiceDisplayResponseHtml() {
      const taskSurfaceHtml = this.voiceTaskSurfaceHtml();
      if (taskSurfaceHtml) return taskSurfaceHtml;

      const raw = this.voiceDisplayResponse();

      if (!raw || raw === 'The latest voice response will appear here.') {
        return '<span class="text-slate-500">' + raw + '</span>';
      }
      if (raw === 'Axon is processing your request…') {
        return '<span class="text-slate-400 voice-typing-cursor">' + raw + '</span>';
      }
      // Use marked.js if available, else escape and linkify
      let html = '';
      if (typeof this.renderMd === 'function') {
        try { html = this.renderMd(raw); } catch { html = ''; }
      } else if (typeof marked !== 'undefined' && marked.parse) {
        try {
          const prepared = typeof this.prepareMarkdownText === 'function' ? this.prepareMarkdownText(raw) : raw;
          html = marked.parse(prepared, { breaks: true });
          if (typeof this.sanitizeRenderedHtml === 'function') {
            html = this.sanitizeRenderedHtml(html);
          }
        } catch {
          html = '';
        }
      }
      if (!html) {
        // Fallback: escape HTML and convert newlines
        html = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      }
      return decorateVoiceResponseLinks(html);
    },

    voiceCanClear() {
      return !!(String(this.voiceTranscript || '').trim() || this.voiceResponseAvailable());
    },

    clearVoiceCommandCenterState() {
      this.clearVoiceTranscript?.();
      this.clearVoiceTextDock?.();
      this.clearVoiceAwaitingReply?.();
      this._voiceResponseDismissedAt = this.voiceLatestResponseMarker();
    },

    voiceStatusLabel() {
      return typeof this.voiceCenterStatusLabel === 'function'
        ? this.voiceCenterStatusLabel()
        : 'Voice command center';
    },

    voiceStateCaption() {
      const override = this.voiceConversationStateCaption?.();
      if (override) return override;
      const state = typeof this.orbState === 'function' ? this.orbState() : 'idle';
      if (this.reactorAsleep) return 'Sleeping - tap to wake';
      if (state === 'listening') return 'Microphone live';
      if (state === 'speaking') return 'Reply playback';
      if (state === 'thinking') return 'Reasoning in progress';
      if (state === 'agent') return 'Agent systems ready';
      return 'Standby';
    },

    voiceStatusHint() {
      if (this.currentWorkspaceRunActive?.()) {
        return 'Say stop to interrupt this run, or give another instruction to steer it. Switch workspace tabs to run another task in parallel.';
      }
      return typeof this.voiceCenterStatusDetail === 'function'
        ? this.voiceCenterStatusDetail()
        : '';
    },

    voiceVisualState() {
      if (this.reactorAsleep) return 'sleep';
      return typeof this.orbState === 'function' ? this.orbState() : 'idle';
    },

    voiceVisualPalette() {
      const state = this.voiceVisualState();
      if (state === 'sleep') {
        return {
          stroke: 'rgba(51, 65, 85, 0.3)',
          glow: 'rgba(0, 0, 0, 0)',
          beamOpacity: 0.08,
          ringOpacity: 0.12,
          strokeWidth: 1.2,
        };
      }
      if (state === 'listening') {
        return {
          stroke: 'rgba(103, 232, 249, 0.92)',
          glow: 'rgba(34, 211, 238, 0.34)',
          beamOpacity: 0.92,
          ringOpacity: 0.78,
          strokeWidth: 2.7,
        };
      }
      if (state === 'speaking') {
        return {
          stroke: 'rgba(191, 219, 254, 0.86)',
          glow: 'rgba(96, 165, 250, 0.3)',
          beamOpacity: 0.82,
          ringOpacity: 0.68,
          strokeWidth: 2.45,
        };
      }
      if (state === 'thinking') {
        return {
          stroke: 'rgba(96, 165, 250, 0.72)',
          glow: 'rgba(59, 130, 246, 0.26)',
          beamOpacity: 0.62,
          ringOpacity: 0.54,
          strokeWidth: 2.2,
        };
      }
      if (state === 'agent') {
        return {
          stroke: 'rgba(251, 191, 36, 0.72)',
          glow: 'rgba(245, 158, 11, 0.22)',
          beamOpacity: 0.58,
          ringOpacity: 0.5,
          strokeWidth: 2,
        };
      }
      return {
        stroke: 'rgba(100, 116, 139, 0.52)',
        glow: 'rgba(71, 85, 105, 0.14)',
        beamOpacity: 0.28,
        ringOpacity: 0.34,
        strokeWidth: 1.8,
      };
    },

    voiceRingStyle(index = 0) {
      const palette = this.voiceVisualPalette();
      const opacity = Math.max(0.16, palette.ringOpacity - (index * 0.16));
      const width = Math.max(1.2, palette.strokeWidth - (index * 0.28));
      return `fill:none;stroke:${palette.stroke};stroke-width:${width};opacity:${opacity};`;
    },

    voiceBeamStyle(multiplier = 1) {
      const palette = this.voiceVisualPalette();
      const opacity = Math.max(0.18, palette.beamOpacity * Number(multiplier || 1));
      return `opacity:${opacity};`;
    },

    voiceGlowStyle() {
      const palette = this.voiceVisualPalette();
      return `fill:${palette.glow};opacity:1;`;
    },

    // ══════════════════════════════════════════════════════════
    // Agent Step Narration — JARVIS-style voice-over during work
    // ══════════════════════════════════════════════════════════

    _lastNarrationAt: 0,
    _narrationQueue: [],
    _narrationTimer: null,

    /**
     * Called by live-operator whenever a new agent step is pushed.
     * Throttled: max 1 narration per 6s to avoid talking over itself.
     */
    narrateAgentStep(phase, title, detail) {
      if (!this.showVoiceOrb || !this.voiceMode) return;
      if (this.reactorAsleep) return;
      // Skip if already speaking a full response or listening
      if (this.voiceActive) return;

      const line = this._buildNarrationLine(phase, title, detail);
      if (!line) return;

      const now = Date.now();
      const elapsed = now - (this._lastNarrationAt || 0);
      const speechBusy = typeof this.voiceSpeechBusy === 'function'
        ? this.voiceSpeechBusy()
        : !!(this._currentAudio || this._speechSynthActive);

      if (elapsed >= 6000 && !speechBusy) {
        this._lastNarrationAt = now;
        this._speakNarration(line);
      } else {
        // Queue the latest line — only keep the most recent pending
        this._narrationQueue = [line];
        if (!this._narrationTimer) {
          const wait = Math.max(500, 6000 - elapsed);
          this._narrationTimer = setTimeout(() => {
            this._narrationTimer = null;
            const queued = this._narrationQueue.shift();
            const queueSpeechBusy = typeof this.voiceSpeechBusy === 'function'
              ? this.voiceSpeechBusy()
              : !!(this._currentAudio || this._speechSynthActive);
            if (queued && this.showVoiceOrb && this.voiceMode
                && !this.voiceActive && !queueSpeechBusy) {
              this._lastNarrationAt = Date.now();
              this._speakNarration(queued);
            }
          }, wait);
        }
      }
    },

    _speakNarration(text) {
      if (typeof this.speakMessage === 'function') {
        this.speakMessage(text);
      }
    },

    _buildNarrationLine(phase, title, detail) {
      const t = String(title || '').trim().toLowerCase();

      // Skip done/complete — autoSpeakResponse handles the final reply
      if (t.includes('complete') || t.includes('finished')) return '';

      if (phase === 'execute') {
        if (t.includes('terminal') || t.includes('command') || t.includes('shell')) {
          return 'Running a terminal command now, Sir.';
        }
        if (t.includes('running')) {
          const toolName = t.replace(/^running\s+/i, '');
          return `Executing ${toolName}.`;
        }
        return 'Working on it, Sir.';
      }
      if (phase === 'verify') {
        if (t.includes('checking')) return 'Reviewing the output now.';
        return '';
      }
      if (phase === 'plan') {
        return 'Planning the next step.';
      }
      if (phase === 'recover') {
        return "There's an issue. I may need your attention, Sir.";
      }
      if (phase === 'observe') {
        return 'Analyzing the workspace now.';
      }
      return '';
    },

    /** Stop narration queue (called when voice orb closes or reactor sleeps) */
    _cancelNarrationQueue() {
      clearTimeout(this._narrationTimer);
      this._narrationTimer = null;
      this._narrationQueue = [];
    },

  };
}

window.axonVoiceCommandCenterMixin = axonVoiceCommandCenterMixin;
