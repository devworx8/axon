/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Control Ring Voice
   Always-listening dashboard voice with a courtesy gate so Axon
   only jumps in when directly addressed or explicitly allowed.
   ══════════════════════════════════════════════════════════════ */

function axonDashboardMiniVoiceMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const clipText = (value = '', max = 160) => {
    const text = trimText(value);
    if (text.length <= max) return text;
    return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
  };
  const escapeRegex = (value = '') => String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const schedule = (callback, delay = 0) => {
    if (typeof window !== 'undefined' && typeof window.setTimeout === 'function') {
      return window.setTimeout(callback, delay);
    }
    return setTimeout(callback, delay);
  };

  const detectWakePhrase = (text = '', wakePhrase = 'Axon') => {
    const transcript = trimText(text).replace(/[“”]/g, '"').replace(/[’]/g, "'");
    const wake = trimText(wakePhrase || 'Axon') || 'Axon';
    if (!transcript) return { matched: false, command: '' };
    const wakePattern = escapeRegex(wake).replace(/\s+/g, '\\s+');
    const match = transcript.match(
      new RegExp(`^(?:(?:hey|ok(?:ay)?|yo|hello|hi|please|listen)\\s+)?${wakePattern}(?:\\b|[,:.!?\\-])\\s*(.*)$`, 'i'),
    );
    if (!match) return { matched: false, command: '' };
    return {
      matched: true,
      command: trimText(String(match[1] || '').replace(/^[,:.!?\-\s]+/, '')),
    };
  };

  const topicMatch = (text = '') => {
    const lower = trimText(text).toLowerCase();
    return [
      'deploy', 'release', 'build', 'preview', 'dns', 'mail', 'email', 'domain',
      'bug', 'issue', 'error', 'failing', 'broken', 'repair', 'fix', 'server',
      'workspace', 'terminal', 'logs', 'cloudflare', 'vercel', 'mobile', 'app', 'scan',
    ].find((token) => lower.includes(token));
  };

  const cueMatch = (text = '') => {
    const lower = trimText(text).toLowerCase();
    return [
      'should we', 'we should', 'can we', 'could we', 'how do we', 'why is', 'what if',
      'not working', 'stuck', 'need to', 'figure out', 'help with',
      'what do you think', 'advice', 'suggestion',
    ].find((token) => lower.includes(token));
  };

  const buildAdvicePrompt = (transcript = '') => {
    const clipped = clipText(transcript, 260);
    return [
      'Offer concise, practical advice for this nearby conversation.',
      'Keep it short, operator-friendly, and focused on the next best move.',
      '',
      `Conversation: ${clipped}`,
    ].join('\n');
  };

  return {
    dashboardMiniVoiceState: {
      passiveArmed: false,
      manualCapture: false,
      resumeTimer: null,
      resumeLocked: false,
      pendingAdvice: null,
      lastHeard: '',
      lastHeardAt: '',
      lastDisposition: '',
      lastDispatchedCommand: '',
    },

    ensureDashboardMiniVoiceState() {
      if (!this.dashboardMiniVoiceState || typeof this.dashboardMiniVoiceState !== 'object') {
        this.dashboardMiniVoiceState = {};
      }
      this.dashboardMiniVoiceState = {
        passiveArmed: false,
        manualCapture: false,
        resumeTimer: null,
        resumeLocked: false,
        pendingAdvice: null,
        lastHeard: '',
        lastHeardAt: '',
        lastDisposition: '',
        lastDispatchedCommand: '',
        ...this.dashboardMiniVoiceState,
      };
      return this.dashboardMiniVoiceState;
    },

    dashboardMiniVoiceDashboardActive() {
      return trimText(this.activeTab || 'dashboard') === 'dashboard';
    },

    dashboardMiniVoiceVoiceReady() {
      return !!(
        this.voiceInputAvailable?.()
        || this.speechInputSupported
        || this.voiceStatus?.transcription_ready
        || this.voiceStatus?.transcription_available
        || this.voiceStatus?.cloud_transcription_available
      );
    },

    dashboardMiniVoiceWakePhrase() {
      return trimText(this.companionAxonWakePhrase?.() || 'Axon') || 'Axon';
    },

    dashboardMiniVoicePassiveArmed() {
      const state = this.ensureDashboardMiniVoiceState();
      return !!state.passiveArmed && this.dashboardMiniVoiceDashboardActive() && !this.showVoiceOrb;
    },

    dashboardMiniVoiceCaptureActive() {
      const state = this.ensureDashboardMiniVoiceState();
      return !!state.manualCapture || this.dashboardMiniVoicePassiveArmed();
    },

    dashboardMiniVoicePendingAdvice() {
      return this.ensureDashboardMiniVoiceState().pendingAdvice || null;
    },

    dashboardMiniVoiceListeningModeLabel() {
      if (this.dashboardMiniVoicePassiveArmed()) return 'Always listening';
      if (this.showVoiceOrb) return 'Full voice mode';
      return 'Tap ring to arm';
    },

    dashboardMiniVoiceCourtesyLabel() {
      return 'Ask before chiming in';
    },

    dashboardMiniVoiceLastHeard() {
      return clipText(this.ensureDashboardMiniVoiceState().lastHeard || '', 150);
    },

    dashboardMiniVoiceLastDispositionLabel() {
      const state = this.ensureDashboardMiniVoiceState();
      const key = trimText(state.lastDisposition).toLowerCase();
      return {
        ambient: 'Ambient conversation ignored',
        'wake-heard': 'Wake word heard',
        'wake-command': 'Wake-word command routed',
        'manual-command': 'Manual command routed',
        'advice-pending': 'Advice waiting for approval',
        'advice-approved': 'Advice approved',
        'advice-dismissed': 'Advice dismissed',
        armed: 'Listening ring armed',
        standby: 'Listening ring idle',
      }[key] || '';
    },

    dashboardMiniVoiceLatestReplyPreview() {
      return trimText(this.latestAssistantResponsePreview?.(220) || '');
    },

    dashboardMiniVoicePanelClass() {
      this.ensureDashboardMiniVoiceState();
      if (this.dashboardMiniVoicePendingAdvice()) return 'dashboard-mini-voice__panel--pending';
      if (this.dashboardMiniVoiceCaptureActive() && this.voiceActive) return 'dashboard-mini-voice__panel--listening';
      if (this.dashboardMiniVoicePassiveArmed()) return 'dashboard-mini-voice__panel--armed';
      if (this.showVoiceOrb) return 'dashboard-mini-voice__panel--expanded';
      if (this.dashboardMiniVoiceVoiceReady()) return 'dashboard-mini-voice__panel--ready';
      return 'dashboard-mini-voice__panel--idle';
    },

    dashboardMiniVoiceRingClass() {
      this.ensureDashboardMiniVoiceState();
      if (this.dashboardMiniVoicePendingAdvice()) return 'mission-ring-control--pending';
      if (this.dashboardMiniVoiceCaptureActive() && this.voiceActive) return 'mission-ring-control--listening';
      if (this.dashboardMiniVoicePassiveArmed()) return 'mission-ring-control--armed';
      return '';
    },

    dashboardMiniVoiceVisualState() {
      if (this.dashboardMiniVoicePendingAdvice()) return 'pending';
      if (this.dashboardMiniVoiceCaptureActive() && this.voiceActive) return 'listening';
      if (this.dashboardMiniVoicePassiveArmed()) return 'armed';
      if (this.chatLoading) return 'thinking';
      return trimText(this.voiceVisualState?.() || 'idle') || 'idle';
    },

    dashboardMiniVoiceStatusLabel() {
      const state = this.ensureDashboardMiniVoiceState();
      if (state.pendingAdvice) return 'Permission pending';
      if (this.dashboardMiniVoiceCaptureActive() && this.voiceActive) return 'Always listening';
      if (this.dashboardMiniVoicePassiveArmed() && (this.chatLoading || state.resumeLocked)) return 'Paused while Axon works';
      if (this.dashboardMiniVoicePassiveArmed()) return 'Wake word armed';
      if (this.showVoiceOrb) return 'Full voice live';
      if (this.dashboardMiniVoiceVoiceReady()) return 'Voice ready';
      return 'Voice pending';
    },

    dashboardMiniVoiceModeLabel() {
      if (this.dashboardMiniVoicePassiveArmed()) return 'Control ring voice';
      if (this.showVoiceOrb) return 'Full voice mode';
      return 'Control ring standby';
    },

    dashboardMiniVoiceStatusDetail() {
      const state = this.ensureDashboardMiniVoiceState();
      if (state.pendingAdvice) {
        return 'Axon caught a topic it can help with, but it will wait for your approval before weighing in.';
      }
      if (this.dashboardMiniVoicePassiveArmed()) {
        return `Always listening is armed. Say "${this.dashboardMiniVoiceWakePhrase()}" to give Axon a command. Nearby conversation stays quiet unless you approve a chime-in.`;
      }
      const detail = trimText(
        this.voiceCenterStatusDetail?.()
        || this.voiceStatusHint?.()
        || this.voiceStatus?.detail,
      );
      if (detail) return detail;
      return 'Arm the ring once, then Axon keeps listening from the dashboard until you disarm it.';
    },

    dashboardMiniVoiceHint() {
      const reply = this.dashboardMiniVoiceLatestReplyPreview();
      if (reply) return reply;
      return 'Talk directly to Axon with the wake phrase, or let Axon ask permission before it offers advice.';
    },

    dashboardMiniVoiceActionLabel() {
      return this.dashboardMiniVoicePassiveArmed() ? 'Disarm ring' : 'Arm ring';
    },

    dashboardMiniVoiceTalkLabel() {
      return this.voiceActive && this.ensureDashboardMiniVoiceState().manualCapture ? 'Stop capture' : 'Talk now';
    },

    _clearDashboardMiniVoiceResume() {
      const state = this.ensureDashboardMiniVoiceState();
      if (state.resumeTimer) clearTimeout(state.resumeTimer);
      state.resumeTimer = null;
    },

    _scheduleDashboardMiniVoiceResume(delay = 600) {
      const state = this.ensureDashboardMiniVoiceState();
      this._clearDashboardMiniVoiceResume();
      if (!state.passiveArmed || !this.dashboardMiniVoiceDashboardActive() || this.showVoiceOrb) return;
      state.resumeTimer = schedule(() => {
        state.resumeTimer = null;
        if (!state.passiveArmed || state.manualCapture || state.resumeLocked || this.showVoiceOrb) return;
        if (!this.dashboardMiniVoiceDashboardActive()) return;
        if (this.chatLoading || this.voiceActive || this.voiceSpeechBusy?.()) {
          this._scheduleDashboardMiniVoiceResume(900);
          return;
        }
        Promise.resolve(this.startVoice?.()).catch(() => {});
      }, Math.max(220, Number(delay || 0)));
    },

    async dashboardMiniVoicePrimaryAction() {
      const state = this.ensureDashboardMiniVoiceState();
      const next = !state.passiveArmed;
      if (!next) {
        state.passiveArmed = false;
        state.manualCapture = false;
        state.resumeLocked = false;
        state.pendingAdvice = null;
        state.lastDisposition = 'standby';
        this._clearDashboardMiniVoiceResume();
        if (this.voiceActive) {
          await this.startVoice?.();
        }
        return false;
      }
      await Promise.resolve(this.loadVoiceStatus?.()).catch(() => {});
      this.refreshVoiceCapability?.();
      if (!this.dashboardMiniVoiceVoiceReady()) {
        this.showToast?.(this.voiceStatus?.detail || 'Voice capture is not ready on this device yet.');
        return false;
      }
      state.passiveArmed = true;
      state.manualCapture = false;
      state.resumeLocked = false;
      state.pendingAdvice = null;
      state.lastDisposition = 'armed';
      if (!this.voiceActive && !this.chatLoading && !this.showVoiceOrb) {
        await this.startVoice?.();
      }
      return true;
    },

    async dashboardMiniVoiceTalkNow() {
      const state = this.ensureDashboardMiniVoiceState();
      await Promise.resolve(this.loadVoiceStatus?.()).catch(() => {});
      this.refreshVoiceCapability?.();
      if (!this.dashboardMiniVoiceVoiceReady()) {
        this.showToast?.(this.voiceStatus?.detail || 'Voice capture is not ready on this device yet.');
        return false;
      }
      state.manualCapture = true;
      state.pendingAdvice = null;
      state.resumeLocked = false;
      state.lastDisposition = 'manual';
      this._clearDashboardMiniVoiceResume();
      if (this.voiceActive) {
        await this.startVoice?.();
      }
      await this.startVoice?.();
      return true;
    },

    dashboardMiniVoiceOpenFull() {
      const state = this.ensureDashboardMiniVoiceState();
      state.manualCapture = false;
      state.resumeLocked = false;
      this._clearDashboardMiniVoiceResume();
      this.openVoiceCommandCenter?.();
    },

    dashboardMiniVoiceSurfaceLabel() {
      return trimText(
        this.dashboardLiveSurfaceModeLabel?.()
        || 'Desktop'
      );
    },

    dashboardMiniVoiceSurfaceDetail() {
      return trimText(
        this.dashboardLiveSurfaceDescription?.()
        || 'Axon will surface the active workspace view here.'
      );
    },

    dashboardMiniVoiceSurfaceActionLabel() {
      return trimText(
        this.dashboardLiveSurfaceActionLabel?.()
        || 'Open'
      );
    },

    async dashboardMiniVoiceSurfaceAction() {
      if (typeof this.dashboardLiveSurfaceAction === 'function') {
        await this.dashboardLiveSurfaceAction();
      }
    },

    async dashboardMiniVoiceDispatchCommand(text = '', options = {}) {
      const command = trimText(text);
      if (!command) return false;
      const state = this.ensureDashboardMiniVoiceState();
      const keepListening = !!state.passiveArmed;
      state.pendingAdvice = null;
      state.manualCapture = false;
      state.resumeLocked = true;
      state.lastDisposition = trimText(options.disposition || 'manual-command') || 'manual-command';
      state.lastDispatchedCommand = command;
      try {
        if (typeof this.sendVoiceCommand === 'function') {
          await this.sendVoiceCommand(command);
        } else {
          this.syncVoiceTranscript?.(command);
          this.chatInput = command;
          await this.sendChat?.();
        }
      } finally {
        state.resumeLocked = false;
        if (keepListening && !this.showVoiceOrb) {
          this._scheduleDashboardMiniVoiceResume(900);
        }
      }
      return true;
    },

    async dashboardMiniVoiceApproveAdvice() {
      const pending = this.dashboardMiniVoicePendingAdvice();
      if (!pending?.prompt) return false;
      return this.dashboardMiniVoiceDispatchCommand(pending.prompt, {
        disposition: 'advice-approved',
      });
    },

    dashboardMiniVoiceDismissAdvice() {
      const state = this.ensureDashboardMiniVoiceState();
      state.pendingAdvice = null;
      state.resumeLocked = false;
      state.lastDisposition = 'advice-dismissed';
      if (state.passiveArmed && !this.showVoiceOrb) {
        this._scheduleDashboardMiniVoiceResume(450);
      }
    },

    handleVoiceCaptureTranscript(text = '', options = {}) {
      const transcript = trimText(text);
      if (!transcript || this.showVoiceOrb) return false;
      if (!this.dashboardMiniVoiceCaptureActive()) return false;
      const state = this.ensureDashboardMiniVoiceState();
      state.lastHeard = transcript;
      state.lastHeardAt = new Date().toISOString();

      if (state.manualCapture) {
        void this.dashboardMiniVoiceDispatchCommand(transcript, {
          disposition: 'manual-command',
        });
        return true;
      }

      const wake = detectWakePhrase(transcript, this.dashboardMiniVoiceWakePhrase());
      if (wake.matched) {
        if (wake.command) {
          void this.dashboardMiniVoiceDispatchCommand(wake.command, {
            disposition: 'wake-command',
          });
        } else {
          state.lastDisposition = 'wake-heard';
          state.resumeLocked = false;
          this.showToast?.(`${this.dashboardMiniVoiceWakePhrase()} is listening.`);
          this._scheduleDashboardMiniVoiceResume(420);
        }
        return true;
      }

      const topic = topicMatch(transcript);
      const cue = cueMatch(transcript);
      if (topic && cue) {
        state.pendingAdvice = {
          topic,
          cue,
          transcript: clipText(transcript, 220),
          prompt: buildAdvicePrompt(transcript),
        };
        state.resumeLocked = true;
        state.lastDisposition = 'advice-pending';
        return true;
      }

      state.lastDisposition = 'ambient';
      this._scheduleDashboardMiniVoiceResume(420);
      return true;
    },

    handleVoiceCaptureLifecycle(eventType = '', payload = {}) {
      if (this.showVoiceOrb) return false;
      if (!this.dashboardMiniVoiceCaptureActive()) return false;
      const state = this.ensureDashboardMiniVoiceState();
      const type = trimText(eventType).toLowerCase();
      const code = trimText(payload.code || payload.reason || payload.message).toLowerCase();

      if (code === 'not-allowed' || code === 'service-not-allowed' || code === 'permission-denied') {
        state.passiveArmed = false;
        state.manualCapture = false;
        state.resumeLocked = false;
        this._clearDashboardMiniVoiceResume();
        return false;
      }

      if (state.manualCapture) {
        state.manualCapture = false;
        return true;
      }

      if (state.resumeLocked) return true;
      if (!state.passiveArmed) return false;
      if (type === 'error' && code && !['no-speech', 'aborted'].includes(code)) return true;

      this._scheduleDashboardMiniVoiceResume(code === 'no-speech' ? 850 : 550);
      return true;
    },
  };
}

window.axonDashboardMiniVoiceMixin = axonDashboardMiniVoiceMixin;
