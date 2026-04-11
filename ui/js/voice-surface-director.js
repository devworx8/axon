/* ══════════════════════════════════════════════════════════════
   Axon — Voice Surface Director
   Focuses the live JARVIS surfaces as Axon moves through work.
   ══════════════════════════════════════════════════════════════ */

function axonVoiceSurfaceDirectorMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const clipText = (value = '', max = 120) => {
    const text = trimText(value);
    return text.length > max ? `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…` : text;
  };
  const scheduleFrame = (callback) => {
    if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(callback);
    try { callback?.(); } catch (_) {}
    return 0;
  };
  const phaseLabel = (value = 'observe') => {
    const normalized = trimText(value).toLowerCase() || 'observe';
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  };
  const toneForType = (type = '') => ({
    approval: 'rose',
    terminal: 'amber',
    browser: 'cyan',
    artifact: 'emerald',
    workspace: 'slate',
    operator: 'cyan',
  }[String(type || '').trim().toLowerCase()] || 'cyan');
  const blankSpotlight = () => ({
    active: false,
    key: '',
    type: '',
    tone: 'cyan',
    eyebrow: '',
    title: '',
    detail: '',
    status: '',
    action: '',
    path: '',
    kind: '',
    phase: '',
    at: '',
  });

  return {
    voiceSurfaceDirector: {
      current: blankSpotlight(),
      history: [],
      timerId: null,
      lastAutoArtifactKey: '',
      lastAutoBrowserKey: '',
    },

    ensureVoiceSurfaceDirectorState() {
      const current = this.voiceSurfaceDirector || {};
      this.voiceSurfaceDirector = {
        current: current.current || blankSpotlight(),
        history: Array.isArray(current.history) ? current.history : [],
        timerId: current.timerId || null,
        lastAutoArtifactKey: trimText(current.lastAutoArtifactKey),
        lastAutoBrowserKey: trimText(current.lastAutoBrowserKey),
        lastAutoTerminalKey: trimText(current.lastAutoTerminalKey),
      };
      return this.voiceSurfaceDirector;
    },

    clearVoiceSurfaceHistory(keepCurrent = true) {
      const state = this.ensureVoiceSurfaceDirectorState();
      state.history = [];
      state.lastAutoArtifactKey = '';
      state.lastAutoBrowserKey = '';
      state.lastAutoTerminalKey = '';
      if (!keepCurrent) state.current = blankSpotlight();
    },

    initVoiceSurfaceDirector() {
      const state = this.ensureVoiceSurfaceDirectorState();
      if (state.timerId || typeof setInterval !== 'function') {
        this.syncVoiceSurfaceDirector?.({ force: true });
        return;
      }
      state.timerId = setInterval(() => {
        try { this.syncVoiceSurfaceDirector?.(); } catch (_) {}
      }, 1200);
      this.syncVoiceSurfaceDirector?.({ force: true });
    },

    stopVoiceSurfaceDirector() {
      const state = this.ensureVoiceSurfaceDirectorState();
      if (state.timerId && typeof clearInterval === 'function') {
        clearInterval(state.timerId);
      }
      state.timerId = null;
    },

    _voiceSurfaceCards() {
      return Array.isArray(this.voiceOperatorSurfaceCards?.(4)) ? this.voiceOperatorSurfaceCards(4) : [];
    },

    _voiceSurfacePhase() {
      return trimText(this.voiceOperatorPhase?.() || this.liveOperator?.phase).toLowerCase() || 'observe';
    },

    _voiceArtifactEntries() {
      return Array.isArray(this.voiceArtifactEntries?.(6)) ? this.voiceArtifactEntries(6) : [];
    },

    _voicePhaseArtifact(phase = 'observe') {
      const artifacts = this._voiceArtifactEntries?.() || [];
      if (!artifacts.length) return null;
      const preferredKinds = {
        observe: ['folder', 'code', 'file', 'pdf', 'image'],
        plan: ['folder', 'code', 'file', 'pdf', 'image'],
        execute: ['code', 'file', 'folder', 'pdf', 'image'],
        verify: ['pdf', 'image', 'code', 'file', 'folder'],
        recover: ['code', 'file', 'pdf', 'folder', 'image'],
      }[trimText(phase).toLowerCase()] || ['file', 'folder', 'pdf', 'image', 'code'];
      for (const kind of preferredKinds) {
        const match = artifacts.find(artifact => trimText(artifact.kind).toLowerCase() === kind && trimText(artifact.path));
        if (match) return match;
      }
      return artifacts.find(artifact => trimText(artifact.path)) || null;
    },

    _voiceArtifactSpotlight(artifact = null, options = {}) {
      if (!artifact || typeof artifact !== 'object') return blankSpotlight();
      const phase = trimText(options.phase || this._voiceSurfacePhase?.() || 'observe').toLowerCase() || 'observe';
      const kind = trimText(artifact.kind || 'file');
      const detail = trimText(options.detail || artifact.detail || artifact.path || 'Live artifact surfaced.');
      const title = trimText(options.title || artifact.title || artifact.path || 'Artifact');
      return {
        active: true,
        key: `artifact:${trimText(artifact.key || artifact.path || title).toLowerCase()}`,
        type: 'artifact',
        tone: toneForType('artifact'),
        eyebrow: trimText(options.eyebrow || (phase === 'verify' ? 'Verification surface' : phase === 'recover' ? 'Repair evidence' : 'Artifact rail')),
        title: clipText(title, 60),
        detail: clipText(detail, 140),
        status: trimText(options.status || `${phaseLabel(phase)} phase`),
        action: trimText(options.action || artifact.action || (kind === 'folder' ? 'Browse' : 'Inspect')),
        path: trimText(artifact.path),
        kind,
        phase,
        at: new Date().toISOString(),
      };
    },

    _voiceSurfaceSpotlightCandidate() {
      const cards = this._voiceSurfaceCards?.() || [];
      const phase = this._voiceSurfacePhase?.() || 'observe';
      const terminalCard = cards.find(card => /terminal/i.test(trimText(card.eyebrow || card.title)));
      const browserCard = cards.find(card => trimText(card.kind).toLowerCase() === 'web');
      const workspaceCard = cards.find(card => /workspace/i.test(trimText(card.eyebrow || '')) || trimText(card.action).toLowerCase().includes('workspace'));
      const phaseArtifact = this._voicePhaseArtifact?.(phase);

      if (this.terminal?.approvalRequired || this.currentPendingAgentApproval?.()) {
        const detail = trimText(this.voiceApprovalSummary?.() || this.liveOperator?.detail || 'Approve or deny the pending action so Axon can continue.');
        return {
          active: true,
          key: `approval:${clipText(detail, 80)}`,
          type: 'approval',
          tone: toneForType('approval'),
          eyebrow: 'Approval gate',
          title: 'Approval required',
          detail,
          status: 'Waiting on you',
          action: this.terminal?.approvalRequired ? 'Open terminal' : 'Review request',
          path: '',
          kind: '',
          phase: 'recover',
          at: new Date().toISOString(),
        };
      }

      if (phase === 'verify' && phaseArtifact) {
        return this._voiceArtifactSpotlight?.(phaseArtifact, {
          phase,
          detail: this.liveOperator?.detail || phaseArtifact.detail || phaseArtifact.path,
          action: trimText(phaseArtifact.action || 'Inspect result'),
        }) || blankSpotlight();
      }

      if (phase === 'recover' && terminalCard && (
        this.voiceTerminalSessionActive?.()
        || this.voiceTerminalTraceActive?.()
        || trimText(this.liveOperator?.detail)
      )) {
        return {
          active: true,
          key: `terminal:${trimText(terminalCard.key || terminalCard.path || terminalCard.title || 'terminal')}`,
          type: 'terminal',
          tone: toneForType('terminal'),
          eyebrow: 'Repair console',
          title: clipText(terminalCard.title || 'Live PTY shell', 60),
          detail: clipText(this.liveOperator?.detail || terminalCard.detail || 'Inspect the live shell to repair the current blocker.', 140),
          status: 'Recover phase',
          action: 'Inspect failure',
          path: trimText(terminalCard.path),
          kind: trimText(terminalCard.kind || 'folder'),
          phase,
          at: new Date().toISOString(),
        };
      }

      if (phase === 'recover' && phaseArtifact) {
        return this._voiceArtifactSpotlight?.(phaseArtifact, {
          phase,
          detail: this.liveOperator?.detail || phaseArtifact.detail || phaseArtifact.path,
          action: 'Inspect evidence',
        }) || blankSpotlight();
      }

      if (terminalCard && (
        this.voiceTerminalSessionActive?.()
        || this.chatLoading
        || this.liveOperator?.active
        || this.voiceConversation?.terminalPinned
      )) {
        return {
          active: true,
          key: `terminal:${trimText(terminalCard.key || terminalCard.path || terminalCard.title || 'terminal')}`,
          type: 'terminal',
          tone: toneForType('terminal'),
          eyebrow: trimText(terminalCard.eyebrow || 'Console terminal'),
          title: clipText(terminalCard.title || 'Live PTY shell', 60),
          detail: clipText(terminalCard.detail || this.voiceTerminalStatusLabel?.() || 'Interactive shell connected.', 140),
          status: trimText(phase === 'execute' ? 'Execute phase' : terminalCard.status || this.voiceTerminalStatusLabel?.() || 'Live shell'),
          action: trimText(phase === 'execute' ? 'Track command' : terminalCard.action || 'Open folder'),
          path: trimText(terminalCard.path),
          kind: trimText(terminalCard.kind || 'folder'),
          phase,
          at: new Date().toISOString(),
        };
      }

      if (browserCard) {
        return {
          active: true,
          key: `browser:${trimText(browserCard.key || browserCard.path || browserCard.title || 'browser')}`,
          type: 'browser',
          tone: toneForType('browser'),
          eyebrow: trimText(browserCard.eyebrow || 'Browser surface'),
          title: clipText(browserCard.title || 'Live page', 60),
          detail: clipText(browserCard.detail || browserCard.path || 'Workspace preview attached.', 140),
          status: trimText(
            phase === 'plan' || phase === 'observe'
              ? `${phaseLabel(phase)} phase`
              : (browserCard.status || this.browserPreviewStatusLabel?.() || 'Attached')
          ),
          action: trimText(
            phase === 'plan' || phase === 'observe'
              ? 'Inspect live page'
              : (browserCard.action || 'Open live page')
          ),
          path: trimText(browserCard.path),
          kind: 'web',
          phase,
          at: new Date().toISOString(),
        };
      }

      if (phaseArtifact) {
        return this._voiceArtifactSpotlight?.(phaseArtifact, { phase }) || blankSpotlight();
      }

      if (workspaceCard) {
        return {
          active: true,
          key: `workspace:${trimText(workspaceCard.path || workspaceCard.title)}`,
          type: 'workspace',
          tone: toneForType('workspace'),
          eyebrow: trimText(workspaceCard.eyebrow || 'Workspace'),
          title: clipText(workspaceCard.title || 'Workspace ready', 60),
          detail: clipText(workspaceCard.detail || workspaceCard.path || 'Current workspace prepared for inspection.', 140),
          status: trimText(workspaceCard.status || 'Ready'),
          action: trimText(workspaceCard.action || 'Browse workspace'),
          path: trimText(workspaceCard.path),
          kind: trimText(workspaceCard.kind || 'folder'),
          phase,
          at: new Date().toISOString(),
        };
      }

      const headline = trimText(this.voiceOperatorHeadline?.() || this.liveOperator?.title);
      if (headline) {
        return {
          active: true,
          key: `operator:${headline.toLowerCase()}`,
          type: 'operator',
          tone: toneForType('operator'),
          eyebrow: 'Operator deck',
          title: clipText(headline, 60),
          detail: clipText(this.voiceOperatorNextStep?.() || this.liveOperator?.detail || 'Tracking the current run.', 140),
          status: trimText(this.voiceOperatorSurfaceChip?.() || this.voiceOperatorPhase?.() || 'Tracking'),
          action: 'Watch telemetry',
          path: '',
          kind: '',
          phase,
          at: new Date().toISOString(),
        };
      }

      return blankSpotlight();
    },

    _voiceNewestArtifact() {
      const artifacts = Array.isArray(this.voiceArtifactEntries?.(6)) ? this.voiceArtifactEntries(6) : [];
      return artifacts.find(artifact => trimText(artifact.path) && trimText(artifact.kind).toLowerCase() !== 'web') || null;
    },

    _recordVoiceSurfaceHistory(spotlight) {
      const state = this.ensureVoiceSurfaceDirectorState();
      const item = {
        key: trimText(spotlight.key),
        type: trimText(spotlight.type),
        tone: trimText(spotlight.tone),
        eyebrow: trimText(spotlight.eyebrow),
        title: trimText(spotlight.title),
        detail: trimText(spotlight.detail),
        status: trimText(spotlight.status),
        action: trimText(spotlight.action),
        path: trimText(spotlight.path),
        kind: trimText(spotlight.kind),
        phase: trimText(spotlight.phase),
        at: trimText(spotlight.at) || new Date().toISOString(),
      };
      if (!item.key) return;
      const last = state.history[state.history.length - 1];
      if (last && last.key === item.key) {
        state.history[state.history.length - 1] = {
          ...last,
          ...item,
          at: item.at,
        };
        return;
      }
      if (last && last.key === item.key && last.status === item.status && last.detail === item.detail) return;
      state.history.push(item);
      if (state.history.length > 8) {
        state.history = state.history.slice(-8);
      }
    },

    voiceSurfaceSpotlight() {
      const state = this.ensureVoiceSurfaceDirectorState();
      return state.current?.active ? state.current : this._voiceSurfaceSpotlightCandidate();
    },

    voiceSurfaceSpotlightTone() {
      return trimText(this.voiceSurfaceSpotlight?.().tone || 'cyan') || 'cyan';
    },

    voiceSurfaceHistory(limit = 4) {
      const state = this.ensureVoiceSurfaceDirectorState();
      return [...state.history].slice(-Math.max(1, limit)).reverse();
    },

    focusVoiceSurfaceSpotlight(target = null) {
      const spotlight = target && typeof target === 'object' ? target : this.voiceSurfaceSpotlight?.();
      if (!spotlight) return;
      const terminalLikeSpotlight = spotlight.type === 'terminal'
        || (spotlight.type === 'approval' && this.voiceTerminalAutoDockActive?.());
      if (terminalLikeSpotlight) {
        if (!this.voiceConversation || typeof this.voiceConversation !== 'object') {
          this.voiceConversation = {};
        }
        if (typeof this.voiceConversation.terminalPinnedTouched !== 'boolean') {
          this.voiceConversation.terminalPinnedTouched = false;
        }
        this.voiceConversation.terminalPinned = true;
        this.syncVoiceCommandCenterRuntime?.();
        scheduleFrame(() => this.focusInteractiveTerminalViewport?.('voice'));
        return;
      }
      const path = trimText(spotlight.path);
      const kind = trimText(spotlight.kind);
      if (!path) return;
      if (spotlight.type === 'browser' || kind === 'web') {
        this.ensureWorkspacePreviewLayout?.(true);
        this.panelBrowserOpen = true;
        return;
      }
      this.openVoiceFileViewer?.(path, kind);
    },

    _maybeAutoDockTerminal(spotlight) {
      const state = this.ensureVoiceSurfaceDirectorState();
      if (!this.showVoiceOrb) return;
      if (!this.voiceConversation || typeof this.voiceConversation !== 'object') {
        this.voiceConversation = {};
      }
      if (typeof this.voiceConversation.terminalPinnedTouched !== 'boolean') {
        this.voiceConversation.terminalPinnedTouched = false;
      }
      if (typeof this.voiceConversation.terminalPinned !== 'boolean') {
        this.voiceConversation.terminalPinned = false;
      }
      const terminalLikeSpotlight = spotlight?.type === 'terminal'
        || (spotlight?.type === 'approval' && this.voiceTerminalAutoDockActive?.());
      if (!terminalLikeSpotlight) {
        if (!this.voiceConversation.terminalPinnedTouched && this.voiceConversation.terminalPinned) {
          this.voiceConversation.terminalPinned = false;
          this.syncVoiceCommandCenterRuntime?.();
        }
        return;
      }
      if (state.lastAutoTerminalKey === spotlight.key && this.voiceConversation.terminalPinned) return;
      state.lastAutoTerminalKey = trimText(spotlight.key);
      if (!this.voiceConversation.terminalPinnedTouched) {
        this.voiceConversation.terminalPinned = true;
      }
      this.syncVoiceCommandCenterRuntime?.();
      scheduleFrame(() => this.focusInteractiveTerminalViewport?.('voice'));
    },

    _maybeAutoSurfaceArtifact(spotlight = null) {
      const state = this.ensureVoiceSurfaceDirectorState();
      if (!this.showVoiceOrb) return;
      if (this.terminal?.approvalRequired || this.currentPendingAgentApproval?.() || this.voiceTerminalAutoDockActive?.()) return;
      const runActive = !!(
        this.chatLoading
        || this.liveOperator?.active
        || this.currentWorkspaceRunActive?.()
      );
      if (!runActive) return;
      const phase = trimText(spotlight?.phase || this._voiceSurfacePhase?.()).toLowerCase() || 'observe';
      if (phase === 'observe' || phase === 'plan') return;
      const artifact = spotlight?.type === 'artifact'
        ? spotlight
        : this._voicePhaseArtifact?.(phase);
      if (!artifact) return;
      const key = trimText(artifact.key || artifact.path || artifact.title || 'artifact');
      if (!key || state.lastAutoArtifactKey === key) return;
      const path = trimText(artifact.path);
      if (!path) return;
      if (this.voiceFileViewer?.open) {
        if (!this.voiceFileViewer?.autoOpened) return;
        if (trimText(this.voiceFileViewer.path) !== path) return;
      }
      if (trimText(this.voiceFileViewer?.path) === path) return;
      state.lastAutoArtifactKey = key;
      this.openVoiceFileViewer?.(path, trimText(artifact.kind || ''), { auto: true });
    },

    _maybeAutoFocusBrowser(spotlight) {
      const state = this.ensureVoiceSurfaceDirectorState();
      if (!this.showVoiceOrb) return;
      if (!spotlight || spotlight.type !== 'browser' || !spotlight.path) return;
      if (state.lastAutoBrowserKey === spotlight.key) return;
      state.lastAutoBrowserKey = spotlight.key;
      this.ensureWorkspacePreviewLayout?.(true);
      this.panelBrowserOpen = true;
    },

    _applyVoiceSurfaceChoreography(spotlight) {
      this._maybeAutoDockTerminal?.(spotlight);
      if (spotlight?.type === 'browser') {
        this._maybeAutoFocusBrowser?.(spotlight);
        return;
      }
      if (spotlight?.type === 'terminal' || spotlight?.type === 'approval') {
        return;
      }
      if (spotlight?.type === 'artifact' || spotlight?.type === 'workspace') {
        this._maybeAutoSurfaceArtifact?.(spotlight);
        return;
      }
      if (spotlight?.type !== 'terminal') {
        this._maybeAutoSurfaceArtifact?.();
      }
    },

    syncVoiceSurfaceDirector(options = {}) {
      const state = this.ensureVoiceSurfaceDirectorState();
      const next = this._voiceSurfaceSpotlightCandidate?.() || blankSpotlight();
      const current = state.current || blankSpotlight();
      const changed = next.key !== current.key || next.status !== current.status || next.detail !== current.detail;
      if (options?.force || changed) {
        state.current = next;
        if (next.active) this._recordVoiceSurfaceHistory?.(next);
      }
      if (!this.showVoiceOrb) return state.current;
      this._applyVoiceSurfaceChoreography?.(state.current);
      return state.current;
    },
  };
}

window.axonVoiceSurfaceDirectorMixin = axonVoiceSurfaceDirectorMixin;
